"""
Profile Repository
Repository layer for working with user profiles.
Encapsulates db.py and provides a clean API.
"""

from typing import Dict, Any, List
from database.db import get_user_profile as db_get_user_profile
from database.db import update_user_profile as db_update_user_profile
from database.db import update_user_notes as db_update_user_notes


class ProfileRepository:
    """
    Repository for managing user profiles.
    """

    @staticmethod
    def get(user_id: int) -> Dict[str, Any]:
        """
        Retrieves the user's profile.
        """
        return db_get_user_profile(user_id)

    @staticmethod
    def update(user_id: int, profile_update: Dict[str, Any]):
        """
        Updates the user profile (moving averages + interests).
        """
        db_update_user_profile(user_id, profile_update)

    @staticmethod
    def add_note(user_id: int, note: str):
        """
        Adds a note to the user.
        """
        db_update_user_notes(user_id, note)

    @staticmethod
    def get_interests(user_id: int) -> List[str]:
        """
        Returns the list of user's interests.
        """
        profile = db_get_user_profile(user_id)
        return profile.get("interests", [])

    @staticmethod
    def get_notes(user_id: int) -> str:
        """
        Returns the user's notes field.
        """
        profile = db_get_user_profile(user_id)
        return profile.get("notes", "")
