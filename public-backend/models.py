"""SQLAlchemy model mapping to the public_forms_v database view."""

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from database import Base


class PublicForm(Base):
    """Read-only model backed by the ``public_forms_v`` database view."""

    __tablename__ = "public_forms_v"
    __table_args__ = {"info": {"is_view": True}}

    # The view has no true primary key.  SQLAlchemy requires one for ORM
    # mapping so we nominate ``title`` which is NOT NULL.  This model is
    # only used for SELECT queries — no inserts/updates.
    title = Column(String(255), primary_key=True)
    form_number = Column(String(70), nullable=True)
    description = Column(Text, nullable=True)
    business_area = Column(String(255), nullable=True)
    keywords = Column(JSONB, nullable=True)
    file_type = Column(String(20), nullable=True)
    effective_date = Column(DateTime, nullable=True)
