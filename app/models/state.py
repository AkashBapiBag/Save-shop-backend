from sqlalchemy import Column, Integer, String

from app.core.database import Base


class IndianState(Base):
    __tablename__ = "indian_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), unique=True, index=True, nullable=False)
    name = Column(String(100), index=True, nullable=False)
    state_type = Column(String(20), nullable=False)  # 'STATE' or 'UT'
    display_name = Column(String(120), nullable=False)
