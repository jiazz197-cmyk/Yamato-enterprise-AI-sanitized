from sqlalchemy import Table, Column, Integer, ForeignKey

from app.models.orm.platform.base import Base

user_role_table = Table(
    'user_roles',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('role_id', Integer, ForeignKey('roles.id'), primary_key=True)
)
