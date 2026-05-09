"""
Profile Repository
Thin re-export layer over db.py used by brain.py.
"""

from database.db import get_user_profile as db_get_user_profile
from database.db import increment_message_count as db_increment_message_count
from database.db import update_user_notes as db_update_user_notes
from database.db import update_user_profile as db_update_user_profile
