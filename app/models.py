from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from datetime import datetime

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True, nullable=False)

    display_name = Column(String, nullable=True)

    # Telegram-style profile information
    bio = Column(String, nullable=True)
    profile_photo_url = Column(String, nullable=True)

    # Privacy settings
    privacy_phone = Column(String, default="everyone")
    privacy_profile_photo = Column(String, default="everyone")
    privacy_last_seen = Column(String, default="everyone")
    privacy_bio = Column(String, default="everyone")

    phone_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_one_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user_two_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id"),
        nullable=False
    )
    sender_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    # Text message body
    message = Column(String, nullable=False, default="")

    # Telegram-style media messages
    media_url = Column(String, nullable=True)
    media_type = Column(String, nullable=True)
    media_name = Column(String, nullable=True)
    media_size = Column(Integer, nullable=True)

    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
