from abc import ABC, abstractmethod
from typing import Dict, List


class ResponseStore(ABC):
    """
    Abstract base class for response message storage systems.
    """

    @abstractmethod
    def add_message(self, message: Dict) -> None:
        """
        Store a response message.

        :param message: Message dictionary containing message_id, session_id, message_body
        :return: None
        """
        pass

    @abstractmethod
    def get_messages(self, session_id: str) -> List[Dict]:
        """
        Retrieve all messages for a session.

        :param session_id: Session ID
        :return: List of message dictionaries
        """
        pass

    @abstractmethod
    def delete_message(self, session_id: str, message_id: str) -> None:
        """
        Delete a specific message.

        :param session_id: Session ID
        :param message_id: Message ID
        :return: None
        """
        pass

    @abstractmethod
    def delete_session(self, session_id: str) -> None:
        """
        Delete all messages in a session.

        :param session_id: Session ID
        :return: None
        """
        pass
