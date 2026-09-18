from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.time import utc_now
from app.models.base import Base


class Questionnaire(Base):
    __tablename__ = "questionnaires"
    __table_args__ = (
        UniqueConstraint("code", name="questionnaires_code_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    user_evaluations = relationship(
        "UserEvaluation",
        back_populates="questionnaire",
        cascade="all, delete-orphan",
    )
    evaluations = relationship("Evaluation", back_populates="questionnaire")


class UserEvaluation(Base):
    __tablename__ = "user_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "evaluatee_id",
            "questionnaire_id",
            "quarter",
            "year",
            name="uq_user_evaluations_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    evaluatee_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    questionnaire_id: Mapped[int] = mapped_column(ForeignKey("questionnaires.id"), index=True)
    quarter: Mapped[str] = mapped_column(String(2), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    is_finalized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    evaluatee = relationship("User")
    questionnaire = relationship("Questionnaire", back_populates="user_evaluations")
    evaluations = relationship(
        "Evaluation",
        back_populates="user_evaluation",
        cascade="all, delete-orphan",
    )


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        UniqueConstraint(
            "user_evaluation_id",
            "evaluator_id",
            name="uq_evaluations_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    evaluator_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    user_evaluation_id: Mapped[int] = mapped_column(ForeignKey("user_evaluations.id"), index=True)
    questionnaire_id: Mapped[int] = mapped_column(ForeignKey("questionnaires.id"), index=True)
    positive_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    improvement_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_data: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    date_submitted: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    evaluator = relationship("User")
    user_evaluation = relationship("UserEvaluation", back_populates="evaluations")
    questionnaire = relationship("Questionnaire", back_populates="evaluations")


class SharedResource(Base):
    __tablename__ = "shared_resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    uploader_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    resource_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_confidential: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    uploader = relationship("User")
    shares = relationship(
        "SharedResourceShare",
        back_populates="resource",
        cascade="all, delete-orphan",
    )
    confidential_access = relationship(
        "SharedResourceConfidentialAccess",
        back_populates="resource",
        cascade="all, delete-orphan",
    )


class SharedResourceShare(Base):
    __tablename__ = "shared_resource_shares"
    __table_args__ = (
        UniqueConstraint("resource_id", "user_id", name="uq_shared_resource_shares_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("shared_resources.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    resource = relationship("SharedResource", back_populates="shares")
    user = relationship("User")


class SharedResourceConfidentialAccess(Base):
    __tablename__ = "shared_resource_confidential_access"
    __table_args__ = (
        UniqueConstraint(
            "resource_id",
            "user_id",
            name="uq_shared_resource_confidential_access_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("shared_resources.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    resource = relationship("SharedResource", back_populates="confidential_access")
    user = relationship("User")


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    author_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    author = relationship("User")


class Poll(Base):
    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    author_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    question: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    allow_multiple_choices: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    author = relationship("User")
    choices = relationship("PollChoice", back_populates="poll", cascade="all, delete-orphan")
    votes = relationship("PollVote", back_populates="poll", cascade="all, delete-orphan")


class PollChoice(Base):
    __tablename__ = "poll_choices"
    __table_args__ = (UniqueConstraint("poll_id", "position", name="uq_poll_choices_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    poll = relationship("Poll", back_populates="choices")
    votes = relationship("PollVote", back_populates="choice", cascade="all, delete-orphan")


class PollVote(Base):
    __tablename__ = "poll_votes"
    __table_args__ = (
        UniqueConstraint("poll_id", "user_id", "choice_id", name="uq_poll_votes_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"), index=True)
    choice_id: Mapped[int] = mapped_column(ForeignKey("poll_choices.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    poll = relationship("Poll", back_populates="votes")
    choice = relationship("PollChoice", back_populates="votes")
    user = relationship("User")
