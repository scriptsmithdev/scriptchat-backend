from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi import (
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    UploadFile,
    File,
    Form
)
from pydantic import BaseModel
from sqlalchemy.orm import Session
from random import randint
from pathlib import Path
import shutil
import mimetypes
import os

from .database import engine, SessionLocal
from .models import Base, User, Conversation, Message


# Create database tables
Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="ScriptChat API",
    description="Private real-time messaging application",
    version="1.0.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




# ============================================================
# SQLITE COMPATIBILITY MIGRATION
# ============================================================

def migrate_database():
    """
    Add newly introduced columns to existing ScriptChat databases.
    SQLAlchemy create_all() does not alter existing tables.
    """

    from sqlalchemy import inspect, text

    inspector = inspect(engine)

    # Users table
    user_columns = {
        column["name"]
        for column in inspector.get_columns("users")
    }

    user_additions = {
        "bio": "TEXT",
        "profile_photo_url": "TEXT",
        "privacy_phone": "TEXT DEFAULT 'everyone'",
        "privacy_profile_photo": "TEXT DEFAULT 'everyone'",
        "privacy_last_seen": "TEXT DEFAULT 'everyone'",
        "privacy_bio": "TEXT DEFAULT 'everyone'",
    }

    with engine.begin() as connection:

        for name, sql_type in user_additions.items():

            if name not in user_columns:

                connection.execute(
                    text(
                        f"ALTER TABLE users ADD COLUMN {name} {sql_type}"
                    )
                )

        # Messages table
        message_columns = {
            column["name"]
            for column in inspector.get_columns("messages")
        }

        message_additions = {
            "media_url": "TEXT",
            "media_type": "TEXT",
            "media_name": "TEXT",
            "media_size": "INTEGER",
        }

        for name, sql_type in message_additions.items():

            if name not in message_columns:

                connection.execute(
                    text(
                        f"ALTER TABLE messages ADD COLUMN {name} {sql_type}"
                    )
                )


migrate_database()

# Temporary OTP storage
# Development only
otp_storage = {}

# ============================================================
# MEDIA STORAGE
# ============================================================

MEDIA_ROOT = Path(__file__).resolve().parent.parent / "media"
PROFILE_MEDIA = MEDIA_ROOT / "profiles"
CHAT_MEDIA = MEDIA_ROOT / "chat"

PROFILE_MEDIA.mkdir(parents=True, exist_ok=True)
CHAT_MEDIA.mkdir(parents=True, exist_ok=True)

# ============================================================
# WEBSOCKET CONNECTION MANAGER
# ============================================================

class ConnectionManager:

    def __init__(self):
        self.active_connections = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int):
        self.active_connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, data: dict):

        websocket = self.active_connections.get(user_id)

        if websocket:
            await websocket.send_json(data)


manager = ConnectionManager()

# Serve uploaded profile photos and chat media
app.mount(
    "/media",
    StaticFiles(directory=str(MEDIA_ROOT)),
    name="media"
)


# ============================================================
# REQUEST MODELS
# ============================================================

class RegisterRequest(BaseModel):
    phone_number: str


class VerifyOTPRequest(BaseModel):
    phone_number: str
    otp: str


class ProfileRequest(BaseModel):
    phone_number: str
    display_name: str



class ProfileUpdateRequest(BaseModel):
    user_id: int
    display_name: str | None = None
    bio: str | None = None


class PrivacyUpdateRequest(BaseModel):
    user_id: int
    privacy_phone: str | None = None
    privacy_profile_photo: str | None = None
    privacy_last_seen: str | None = None
    privacy_bio: str | None = None

class ConversationRequest(BaseModel):
    user_one_id: int
    user_two_id: int


class MessageRequest(BaseModel):
    conversation_id: int
    sender_id: int
    message: str


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():

    return {
        "application": "ScriptChat",
        "message": "Welcome to ScriptChat",
        "status": "online",
        "version": "1.0.0"
    }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "healthy"
    }


# ============================================================
# REGISTER
# ============================================================

@app.post("/register")
def register(request: RegisterRequest):

    db: Session = SessionLocal()

    existing_user = (
        db.query(User)
        .filter(User.phone_number == request.phone_number)
        .first()
    )

    if existing_user:

        db.close()

        raise HTTPException(
            status_code=400,
            detail="Phone number already registered"
        )

    # Generate six digit OTP
    otp = str(randint(100000, 999999))

    # Store OTP temporarily
    otp_storage[request.phone_number] = otp

    # Development only
    print(
        f"\n[DEV OTP] {request.phone_number} → {otp}\n"
    )

    db.close()

    return {
        "message": "OTP generated",
        "phone_number": request.phone_number,
        "development_note": "OTP is displayed in the server terminal"
    }


# ============================================================
# LOGIN
# ============================================================

@app.post("/login")
def login(request: RegisterRequest):

    db: Session = SessionLocal()

    existing_user = (
        db.query(User)
        .filter(User.phone_number == request.phone_number)
        .first()
    )

    if not existing_user:

        db.close()

        raise HTTPException(
            status_code=404,
            detail="Phone number not registered. Please register first."
        )

    # Generate six digit OTP
    otp = str(randint(100000, 999999))

    # Store OTP temporarily
    otp_storage[request.phone_number] = otp

    # Development only
    print(
        f"\n[DEV LOGIN OTP] {request.phone_number} → {otp}\n"
    )

    db.close()

    return {
        "message": "Login OTP generated",
        "phone_number": request.phone_number,
        "development_note": "OTP is displayed in the server terminal"
    }


# ============================================================
# VERIFY OTP
# ============================================================

@app.post("/verify-otp")
def verify_otp(request: VerifyOTPRequest):

    stored_otp = otp_storage.get(request.phone_number)

    if not stored_otp:

        raise HTTPException(
            status_code=400,
            detail="No OTP found. Please request a new OTP."
        )

    if request.otp != stored_otp:

        raise HTTPException(
            status_code=400,
            detail="Invalid OTP"
        )

    db: Session = SessionLocal()

    # Check whether this phone number already belongs
    # to an existing user.
    existing_user = (
        db.query(User)
        .filter(User.phone_number == request.phone_number)
        .first()
    )

    if existing_user:

        # Existing user = LOGIN
        existing_user.phone_verified = True

        db.commit()
        db.refresh(existing_user)

        del otp_storage[request.phone_number]

        db.close()

        return {
            "message": "Login successful",
            "user_id": existing_user.id,
            "phone_number": existing_user.phone_number,
            "display_name": existing_user.display_name,
            "verified": True
        }

    # No existing user = REGISTRATION
    user = User(
        phone_number=request.phone_number,
        phone_verified=True
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    # Delete OTP after successful registration
    del otp_storage[request.phone_number]

    db.close()

    return {
        "message": "Phone number verified successfully",
        "user_id": user.id,
        "phone_number": user.phone_number,
        "display_name": user.display_name,
        "verified": True
    }


# ============================================================
# CREATE PROFILE
# ============================================================

@app.post("/profile")
def create_profile(request: ProfileRequest):

    db: Session = SessionLocal()

    user = (
        db.query(User)
        .filter(User.phone_number == request.phone_number)
        .first()
    )

    if not user:

        db.close()

        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if not user.phone_verified:

        db.close()

        raise HTTPException(
            status_code=403,
            detail="Phone number is not verified"
        )

    user.display_name = request.display_name

    db.commit()
    db.refresh(user)

    db.close()

    return {
        "message": "Profile created successfully",
        "user_id": user.id,
        "phone_number": user.phone_number,
        "display_name": user.display_name
    }


# ============================================================
# GET USERS
# ============================================================

@app.get("/users")
def get_users():

    db: Session = SessionLocal()

    users = db.query(User).all()

    result = []

    for user in users:

        result.append({
            "id": user.id,
            "phone_number": user.phone_number,
            "display_name": user.display_name,
            "bio": user.bio,
            "profile_photo_url": user.profile_photo_url,
            "verified": user.phone_verified
        })

    db.close()

    return {
        "users": result
    }


# ============================================================
# CREATE CONVERSATION
# ============================================================

@app.post("/conversations")
def create_conversation(request: ConversationRequest):

    db: Session = SessionLocal()

    # Check both users exist
    user_one = (
        db.query(User)
        .filter(User.id == request.user_one_id)
        .first()
    )

    user_two = (
        db.query(User)
        .filter(User.id == request.user_two_id)
        .first()
    )

    if not user_one or not user_two:

        db.close()

        raise HTTPException(
            status_code=404,
            detail="One or both users do not exist"
        )

    # Prevent user from messaging themselves
    if request.user_one_id == request.user_two_id:

        db.close()

        raise HTTPException(
            status_code=400,
            detail="You cannot create a conversation with yourself"
        )

    # Check if conversation already exists
    existing = (
        db.query(Conversation)
        .filter(
            (
                (Conversation.user_one_id == request.user_one_id)
                &
                (Conversation.user_two_id == request.user_two_id)
            )
            |
            (
                (Conversation.user_one_id == request.user_two_id)
                &
                (Conversation.user_two_id == request.user_one_id)
            )
        )
        .first()
    )

    if existing:

        db.close()

        return {
            "message": "Conversation already exists",
            "conversation_id": existing.id
        }

    conversation = Conversation(
        user_one_id=request.user_one_id,
        user_two_id=request.user_two_id
    )

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    db.close()

    return {
        "message": "Conversation created",
        "conversation_id": conversation.id,
        "user_one_id": conversation.user_one_id,
        "user_two_id": conversation.user_two_id
    }


# ============================================================
# GET CONVERSATION
# ============================================================

@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int):

    db: Session = SessionLocal()

    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id)
        .first()
    )

    if not conversation:

        db.close()

        raise HTTPException(
            status_code=404,
            detail="Conversation not found"
        )

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    result = []

    for message in messages:

        result.append({
            "id": message.id,
            "sender_id": message.sender_id,
            "message": message.message,
            "media_url": message.media_url,
            "media_type": message.media_type,
            "media_name": message.media_name,
            "media_size": message.media_size,
            "is_read": message.is_read,
            "created_at": message.created_at
        })

    db.close()

    return {
        "conversation_id": conversation.id,
        "user_one_id": conversation.user_one_id,
        "user_two_id": conversation.user_two_id,
        "messages": result
    }


# ============================================================
# SEND MESSAGE
# ============================================================

@app.post("/messages")
def send_message(request: MessageRequest):

    db: Session = SessionLocal()

    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == request.conversation_id)
        .first()
    )

    if not conversation:

        db.close()

        raise HTTPException(
            status_code=404,
            detail="Conversation not found"
        )

    sender = (
        db.query(User)
        .filter(User.id == request.sender_id)
        .first()
    )

    if not sender:

        db.close()

        raise HTTPException(
            status_code=404,
            detail="Sender not found"
        )

    # Make sure sender belongs to conversation
    if request.sender_id not in [
        conversation.user_one_id,
        conversation.user_two_id
    ]:

        db.close()

        raise HTTPException(
            status_code=403,
            detail="Sender is not part of this conversation"
        )

    # Prevent empty messages
    if not request.message.strip():

        db.close()

        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty"
        )

    message = Message(
        conversation_id=request.conversation_id,
        sender_id=request.sender_id,
        message=request.message.strip()
    )

    db.add(message)
    db.commit()
    db.refresh(message)

    db.close()

    return {
        "message": "Message sent",
        "message_id": message.id,
        "conversation_id": message.conversation_id,
        "sender_id": message.sender_id,
        "text": message.message,
        "is_read": message.is_read,
        "created_at": message.created_at
    }


# ============================================================
# MARK MESSAGE AS READ
# ============================================================

@app.put("/messages/{message_id}/read")
def mark_message_read(message_id: int):

    db: Session = SessionLocal()

    message = (
        db.query(Message)
        .filter(Message.id == message_id)
        .first()
    )

    if not message:

        db.close()

        raise HTTPException(
            status_code=404,
            detail="Message not found"
        )

    message.is_read = True

    db.commit()
    db.refresh(message)

    db.close()

    return {
        "message": "Message marked as read",
        "message_id": message.id,
        "is_read": True
    }


# ============================================================
# GET ALL CONVERSATIONS
# ============================================================

@app.get("/conversations")
def get_conversations():

    db: Session = SessionLocal()

    conversations = db.query(Conversation).all()

    result = []

    for conversation in conversations:

        result.append({
            "id": conversation.id,
            "user_one_id": conversation.user_one_id,
            "user_two_id": conversation.user_two_id,
            "created_at": conversation.created_at
        })

    db.close()

    return {
        "conversations": result
    }
# ============================================================
# GET USER CONVERSATIONS
# ============================================================

@app.get("/users/{user_id}/conversations")
def get_user_conversations(user_id: int):

    db: Session = SessionLocal()

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if not user:
        db.close()

        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    conversations = (
        db.query(Conversation)
        .filter(
            (Conversation.user_one_id == user_id)
            |
            (Conversation.user_two_id == user_id)
        )
        .order_by(
            Conversation.created_at.desc()
        )
        .all()
    )

    result = []

    for conversation in conversations:

        # Determine the other participant
        if conversation.user_one_id == user_id:
            other_user_id = conversation.user_two_id
        else:
            other_user_id = conversation.user_one_id

        other_user = (
            db.query(User)
            .filter(User.id == other_user_id)
            .first()
        )

        # Get the latest message
        latest_message = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation.id
            )
            .order_by(
                Message.created_at.desc()
            )
            .first()
        )

        # Count unread messages sent by the other user
        unread_count = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation.id,
                Message.sender_id != user_id,
                Message.is_read == False
            )
            .count()
        )

        result.append({
            "conversation_id": conversation.id,

            "other_user": {
                "id": other_user.id if other_user else None,
                "display_name": (
                    other_user.display_name
                    if other_user and other_user.display_name
                    else "ScriptChat User"
                ),
                "phone_number": (
                    other_user.phone_number
                    if other_user
                    else None
                )
            },

            "latest_message": (
                latest_message.message
                if latest_message
                else None
            ),

            "latest_message_sender_id": (
                latest_message.sender_id
                if latest_message
                else None
            ),

            "latest_message_created_at": (
                latest_message.created_at.isoformat()
                if latest_message
                else None
            ),

            "unread_count": unread_count,

            "created_at": conversation.created_at.isoformat()
        })

    db.close()

    return {
        "conversations": result
    }



# ============================================================
# GET PROFILE
# ============================================================

@app.get("/users/{user_id}/profile")
def get_profile(user_id: int):

    db: Session = SessionLocal()

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if not user:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    result = {
        "id": user.id,
        "phone_number": user.phone_number,
        "display_name": user.display_name,
        "bio": user.bio,
        "profile_photo_url": user.profile_photo_url,
        "privacy": {
            "phone": user.privacy_phone or "everyone",
            "profile_photo": user.privacy_profile_photo or "everyone",
            "last_seen": user.privacy_last_seen or "everyone",
            "bio": user.privacy_bio or "everyone",
        },
        "phone_verified": user.phone_verified,
    }

    db.close()

    return result


# ============================================================
# UPDATE PROFILE
# ============================================================

@app.put("/users/{user_id}/profile")
def update_profile(
    user_id: int,
    request: ProfileUpdateRequest
):

    if request.user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="User ID mismatch"
        )

    db: Session = SessionLocal()

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if not user:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if request.display_name is not None:
        name = request.display_name.strip()

        if len(name) > 100:
            db.close()
            raise HTTPException(
                status_code=400,
                detail="Display name is too long"
            )

        user.display_name = name

    if request.bio is not None:

        bio = request.bio.strip()

        if len(bio) > 255:
            db.close()
            raise HTTPException(
                status_code=400,
                detail="Bio is too long"
            )

        user.bio = bio

    db.commit()
    db.refresh(user)

    result = {
        "message": "Profile updated",
        "user_id": user.id,
        "display_name": user.display_name,
        "bio": user.bio,
        "profile_photo_url": user.profile_photo_url,
    }

    db.close()

    return result


# ============================================================
# PROFILE PHOTO UPLOAD
# ============================================================

@app.post("/users/{user_id}/profile-photo")
async def upload_profile_photo(
    user_id: int,
    file: UploadFile = File(...)
):

    db: Session = SessionLocal()

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if not user:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    content_type = file.content_type or ""

    # Some mobile platforms send image files as application/octet-stream.
    # Fall back to the filename extension.
    if content_type == "application/octet-stream":
        filename_lower = (file.filename or "").lower()

        if filename_lower.endswith((".jpg", ".jpeg")):
            content_type = "image/jpeg"
        elif filename_lower.endswith(".png"):
            content_type = "image/png"
        elif filename_lower.endswith(".webp"):
            content_type = "image/webp"
        elif filename_lower.endswith(".gif"):
            content_type = "image/gif"

    print(
        f"PROFILE PHOTO: filename={file.filename}, "
        f"content_type={content_type}"
    )

    allowed = {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    }

    if content_type not in allowed:
        db.close()
        raise HTTPException(
            status_code=400,
            detail="Only JPG, PNG, WEBP or GIF profile photos are allowed"
        )

    extension = mimetypes.guess_extension(content_type) or ".jpg"

    filename = f"user_{user_id}_{randint(100000,999999)}{extension}"

    destination = PROFILE_MEDIA / filename

    with destination.open("wb") as output:
        while True:
            chunk = await file.read(1024 * 1024)

            if not chunk:
                break

            output.write(chunk)

    user.profile_photo_url = f"/media/profiles/{filename}"

    db.commit()
    db.refresh(user)

    result = {
        "message": "Profile photo updated",
        "profile_photo_url": user.profile_photo_url
    }

    db.close()

    return result


# ============================================================
# PRIVACY SETTINGS
# ============================================================

@app.put("/users/{user_id}/privacy")
def update_privacy(
    user_id: int,
    request: PrivacyUpdateRequest
):

    if request.user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="User ID mismatch"
        )

    valid = {"everyone", "contacts", "nobody"}

    values = {
        "privacy_phone": request.privacy_phone,
        "privacy_profile_photo": request.privacy_profile_photo,
        "privacy_last_seen": request.privacy_last_seen,
        "privacy_bio": request.privacy_bio,
    }

    for key, value in values.items():

        if value is not None and value not in valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid privacy value for {key}"
            )

    db: Session = SessionLocal()

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if not user:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    for key, value in values.items():

        if value is not None:
            setattr(user, key, value)

    db.commit()
    db.refresh(user)

    result = {
        "message": "Privacy settings updated",
        "privacy": {
            "phone": user.privacy_phone or "everyone",
            "profile_photo": user.privacy_profile_photo or "everyone",
            "last_seen": user.privacy_last_seen or "everyone",
            "bio": user.privacy_bio or "everyone",
        }
    }

    db.close()

    return result


# ============================================================
# UPLOAD CHAT MEDIA
# ============================================================

@app.post("/conversations/{conversation_id}/media")
async def upload_chat_media(
    conversation_id: int,
    sender_id: int = Form(...),
    message: str = Form(""),
    file: UploadFile = File(...)
):

    db: Session = SessionLocal()

    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id)
        .first()
    )

    if not conversation:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Conversation not found"
        )

    if sender_id not in [
        conversation.user_one_id,
        conversation.user_two_id
    ]:
        db.close()
        raise HTTPException(
            status_code=403,
            detail="You are not part of this conversation"
        )

    content_type = file.content_type or "application/octet-stream"

    if content_type.startswith("image/"):
        media_type = "image"

    elif content_type.startswith("video/"):
        media_type = "video"

    else:
        db.close()
        raise HTTPException(
            status_code=400,
            detail="Only image and video files are currently supported"
        )

    extension = (
        Path(file.filename or "").suffix
        or mimetypes.guess_extension(content_type)
        or ".bin"
    )

    filename = (
        f"chat_{conversation_id}_"
        f"{sender_id}_{randint(100000,999999)}"
        f"{extension}"
    )

    destination = CHAT_MEDIA / filename

    total_size = 0

    with destination.open("wb") as output:

        while True:

            chunk = await file.read(1024 * 1024)

            if not chunk:
                break

            total_size += len(chunk)

            # Development safety limit: 100 MB
            if total_size > 100 * 1024 * 1024:

                output.close()

                destination.unlink(missing_ok=True)

                db.close()

                raise HTTPException(
                    status_code=413,
                    detail="Media file is larger than 100 MB"
                )

            output.write(chunk)

    new_message = Message(
        conversation_id=conversation_id,
        sender_id=sender_id,
        message=message.strip() or "",
        media_url=f"/media/chat/{filename}",
        media_type=media_type,
        media_name=file.filename,
        media_size=total_size,
        is_read=False
    )

    db.add(new_message)
    db.commit()
    db.refresh(new_message)

    if sender_id == conversation.user_one_id:
        recipient_id = conversation.user_two_id
    else:
        recipient_id = conversation.user_one_id

    message_data = {
        "type": "message",
        "message_id": new_message.id,
        "conversation_id": conversation_id,
        "sender_id": sender_id,
        "message": new_message.message,
        "media_url": new_message.media_url,
        "media_type": new_message.media_type,
        "media_name": new_message.media_name,
        "media_size": new_message.media_size,
        "is_read": False,
        "created_at": new_message.created_at.isoformat()
    }

    db.close()

    await manager.send_to_user(
        recipient_id,
        message_data
    )

    await manager.send_to_user(
        sender_id,
        message_data
    )

    return message_data


# ============================================================
# REAL-TIME WEBSOCKET CHAT
# ============================================================

class ConnectionManager:

    def __init__(self):
        self.active_connections = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int):
        self.active_connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, data: dict):

        websocket = self.active_connections.get(user_id)

        if websocket:
            await websocket.send_json(data)


manager = ConnectionManager()


@app.websocket("/ws/{user_id}")
async def websocket_chat(
    websocket: WebSocket,
    user_id: int
):

    await manager.connect(user_id, websocket)

    try:

        while True:

            # Wait for message from client
            data = await websocket.receive_json()

            print(f"WEBSOCKET RECEIVED from user {user_id}: {data}", flush=True)

            conversation_id = data.get("conversation_id")
            message_text = data.get("message")

            if not conversation_id:
                await websocket.send_json({
                    "type": "error",
                    "message": "conversation_id is required"
                })
                continue

            if not message_text:
                await websocket.send_json({
                    "type": "error",
                    "message": "message is required"
                })
                continue

            db: Session = SessionLocal()

            try:

                # Find conversation
                conversation = (
                    db.query(Conversation)
                    .filter(
                        Conversation.id == conversation_id
                    )
                    .first()
                )

                if not conversation:

                    await websocket.send_json({
                        "type": "error",
                        "message": "Conversation not found"
                    })

                    continue

                # Make sure sender belongs to conversation
                if user_id not in [
                    conversation.user_one_id,
                    conversation.user_two_id
                ]:

                    await websocket.send_json({
                        "type": "error",
                        "message": "You are not part of this conversation"
                    })

                    continue

                # Determine recipient
                if user_id == conversation.user_one_id:
                    recipient_id = conversation.user_two_id
                else:
                    recipient_id = conversation.user_one_id

                # Create message
                new_message = Message(
                    conversation_id=conversation_id,
                    sender_id=user_id,
                    message=message_text.strip(),
                    is_read=False
                )

                db.add(new_message)
                db.commit()
                db.refresh(new_message)

                # Prepare response
                message_data = {
                    "type": "message",
                    "message_id": new_message.id,
                    "conversation_id": conversation_id,
                    "sender_id": user_id,
                    "message": new_message.message,
                    "media_url": new_message.media_url,
                    "media_type": new_message.media_type,
                    "media_name": new_message.media_name,
                    "media_size": new_message.media_size,
                    "is_read": False,
                    "created_at": new_message.created_at.isoformat()
                }

            finally:

                db.close()

            # Send message to recipient
            await manager.send_to_user(
                recipient_id,
                message_data
            )

            # Send confirmation to sender
            await manager.send_to_user(
                user_id,
                message_data
            )

    except WebSocketDisconnect:

        manager.disconnect(user_id)

    except Exception as error:

        print(f"WebSocket error for user {user_id}: {error}")

        manager.disconnect(user_id)
