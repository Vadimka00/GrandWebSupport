# models.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from config import DATABASE_URL 

engine = create_async_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)         # Telegram ID
    username = Column(String(100))                    # @username
    full_name = Column(String(255))                   # Имя + фамилия
    language_code = Column(String(2))                 # 'ru' / 'en'
    role = Column(String(50), default='user')         # 'user' / 'moderator'

    # Явно указываем, что это связь по полю SupportRequest.user_id
    requests = relationship(
        "SupportRequest",
        back_populates="user",
        foreign_keys="[SupportRequest.user_id]"
    )
    credentials = relationship("Credentials", uselist=False, back_populates="user")

class SupportRequest(Base):
    __tablename__ = "support_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    assigned_moderator_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)

    status = Column(String(20), default='pending')  # pending / in_progress / closed
    language = Column(String(2))  # 'ru' or 'en'
    created_at = Column(DateTime, default=datetime.utcnow)
    taken_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

    # Связь на пользователя, отправившего запрос
    user = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="requests"
    )
    # Дополнительная связь, чтобы легко получить назначенного модератора
    moderator = relationship(
        "User",
        foreign_keys=[assigned_moderator_id]
    )
    messages = relationship("MessageHistory", back_populates="request")
    

class MessageHistory(Base):
    __tablename__ = "message_history"

    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("support_requests.id"))
    sender_id = Column(BigInteger, ForeignKey("users.id"))
    text = Column(Text, nullable=True)
    photo_file_id = Column(String(255), nullable=True)
    caption = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    request = relationship("SupportRequest", back_populates="messages")

class Translation(Base):
    __tablename__ = "translations"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), index=True)
    lang = Column(String(2))
    text = Column(Text)


class Language(Base):
    __tablename__ = "languages"

    code = Column(String(10), primary_key=True)
    name = Column(String(50), nullable=False)
    emoji = Column(String(10), default="")
    available = Column(Boolean, default=True)

class Status(Base):
    __tablename__ = "status"

    id = Column(BigInteger, primary_key=True)         # Telegram ID
    language_code = Column(String(2))                 # 'ru' / 'en'
    role = Column(String(50))
    text = Column(Text, nullable=True) 

class Credentials(Base):
    __tablename__ = "credentials"

    user_id       = Column(BigInteger, ForeignKey("users.id"), primary_key=True)
    email         = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)

    user = relationship("User", back_populates="credentials")