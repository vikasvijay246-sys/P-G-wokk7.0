import logging
"""
from api.utils import ok, fail, paginate, safe_route
api/chat.py — Chat REST endpoints
Actual real-time is handled by sockets/chat_socket.py
Messages are E2E encrypted: server stores ciphertext only
"""

import os, uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from extensions import db
from db_models import Message, User, Notification

chat_bp = Blueprint("chat", __name__, url_prefix="/api/chat")


def _save_file(field):
    f = request.files.get(field)
    if not f or not f.filename:
        return None, None, None
    ext = f.filename.rsplit(".", 1)[-1].lower()
    if ext not in current_app.config["ALLOWED_FILE_EXTENSIONS"]:
        return None, None, f.filename
    name = f"{uuid.uuid4().hex}.{ext}"
    f.save(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
    ftype = "image" if ext in {"jpg", "jpeg", "png", "gif", "webp"} else "file"
    return f"/static/uploads/{name}", ftype, f.filename


# ── Conversation list for logged-in user ──────────────────
@chat_bp.route("/conversations", methods=["GET"])
@jwt_required()
def conversations():
    uid = int(get_jwt_identity())

    # Get all unique users this person has chatted with
    sent_to   = db.session.query(Message.receiver_id).filter_by(sender_id=uid).distinct()
    recv_from = db.session.query(Message.sender_id).filter_by(receiver_id=uid).distinct()

    peer_ids = set()
    for r in sent_to:  peer_ids.add(r[0])
    for r in recv_from: peer_ids.add(r[0])

    result = []
    for pid in peer_ids:
        peer = User.query.get(pid)
        if not peer:
            continue
        # Last message
        last = (Message.query.filter(
            db.or_(
                db.and_(Message.sender_id == uid, Message.receiver_id == pid),
                db.and_(Message.sender_id == pid, Message.receiver_id == uid)
            )
        ).order_by(Message.created_at.desc()).first())

        # Unread count
        unread = Message.query.filter_by(
            sender_id=pid, receiver_id=uid, status="delivered"
        ).count()

        result.append({
            "peer": peer.to_dict(),
            "last_message": last.to_dict() if last else None,
            "unread_count": unread,
        })

    # Sort by last message time
    result.sort(key=lambda x: x["last_message"]["created_at"]
                if x["last_message"] else "", reverse=True)
    return jsonify(result)


# ── Message history between two users ─────────────────────
@chat_bp.route("/history/<int:peer_id>", methods=["GET"])
@jwt_required()
def history(peer_id):
    uid = int(get_jwt_identity())
    page = int(request.args.get("page", 1))
    per  = int(request.args.get("per_page", 30))

    msgs = (Message.query.filter(
        db.or_(
            db.and_(Message.sender_id == uid, Message.receiver_id == peer_id),
            db.and_(Message.sender_id == peer_id, Message.receiver_id == uid)
        )
    ).order_by(Message.created_at.desc())
     .offset((page - 1) * per).limit(per).all())

    # Mark as seen
    unread = Message.query.filter_by(
        sender_id=peer_id, receiver_id=uid, status="delivered"
    ).all()
    for m in unread:
        m.status = "seen"
        m.seen_at = datetime.utcnow()
    db.session.commit()

    return jsonify(list(reversed([m.to_dict() for m in msgs])))


# ── Send a message (REST fallback if socket unavailable) ──
@chat_bp.route("/send", methods=["POST"])
@jwt_required()
def send_message():
    uid = int(get_jwt_identity())

    is_mp = request.content_type and "multipart" in request.content_type
    data = request.form if is_mp else (request.get_json() or {})

    receiver_id = int(data.get("receiver_id", 0))
    content_enc = data.get("content_encrypted", "")
    iv          = data.get("iv", "")

    if not receiver_id:
        return jsonify({"error": "receiver_id required"}), 400

    receiver = User.query.get_or_404(receiver_id)

    file_url = file_type = file_name = None
    if is_mp:
        file_url, file_type, file_name = _save_file("file")

    msg = Message(
        sender_id=uid,
        receiver_id=receiver_id,
        content_encrypted=content_enc,
        iv=iv,
        file_url=file_url,
        file_type=file_type,
        file_name=file_name,
        status="delivered",
        created_at=datetime.utcnow(),
        delivered_at=datetime.utcnow(),
    )
    db.session.add(msg)

    # Notification for receiver
    sender = User.query.get(uid)
    db.session.add(Notification(
        user_id=receiver_id,
        notif_type="new_message",
        title=f"Message from {sender.name if sender else 'Someone'}",
        body="New message received",
        data_json=f'{{"sender_id":{uid}}}'
    ))
    db.session.commit()
    return jsonify({"success": True, "message": msg.to_dict()}), 201


# ── Get peer's public key (for E2E encryption) ───────────
@chat_bp.route("/pubkey/<int:peer_id>", methods=["GET"])
@jwt_required()
def get_pubkey(peer_id):
    peer = User.query.get_or_404(peer_id)
    return jsonify({"user_id": peer.id, "public_key": peer.public_key})
