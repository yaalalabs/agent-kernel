import os
from typing import Any, Dict, Iterable, List, Mapping

import trino
from base import KnowledgeBase

# from openai_model import model

STARBURST_HOST = os.getenv("STARBURST_HOST", "")
STARBURST_USER = os.getenv("STARBURST_USER", "")
STARBURST_PASSWORD = os.getenv("STARBURST_PASSWORD", "")
STARBURST_CATALOG = os.getenv("STARBURST_CATALOG", "")


class StarburstManager(KnowledgeBase):
    def __init__(self):
        self.host = STARBURST_HOST
        self.user = STARBURST_USER
        self.password = STARBURST_PASSWORD
        self.catalog = STARBURST_CATALOG

    def connect(self):
        """Opens the secure tunnel to the Starburst Trino engi
        ne."""
        return trino.dbapi.connect(
            host=self.host,
            port=443,
            user=self.user,
            catalog=self.catalog,
            http_scheme="https",
            auth=trino.auth.BasicAuthentication(self.user, self.password),
        )

    def write(self, records: Iterable[Mapping[str, Any]], **kwargs) -> None:
        """
        In this MVP, the Google Sheet acts as a Read-Only live database for the Agent.
        To 'add' records, a human simply types them into the Google Sheet UI.
        """
        print("Info: Starburst Google Sheets connector is read-only. Please edit the Sheet directly.")
        pass

    def read(self, query: str, limit: int = 3, **kwargs) -> List[Dict[str, Any]]:
        try:
            conn = self.connect()
            cursor = conn.cursor()

            safe_query = query.replace("'", "''")

            sheet_id = "1ND7S86ni14J-0hVYIrBs3zIUPMkKoT0YGmvyLLHhDDY"

            sql = f"""
                SELECT topic, information, department 
                FROM TABLE({self.catalog}.system.sheet(id => '{sheet_id}')) 
                WHERE LOWER(topic) LIKE LOWER('%{safe_query}%') 
                   OR LOWER(information) LIKE LOWER('%{safe_query}%')
                LIMIT {limit}
            """

            cursor.execute(sql)

            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            cursor.close()

            normalized_results = []
            for row in rows:
                row_dict = dict(zip(columns, row))

                text_content = f"Topic: {row_dict.get('topic', 'N/A')} | Info: {row_dict.get('information', 'N/A')}"

                metadata = {"department": row_dict.get("department", "N/A"), "source": "Google Sheets Data Lake"}

                normalized_results.append({"text": text_content, "metadata": metadata})

            return normalized_results

        except Exception as e:
            print(f"Starburst query error: {e}")
            return []
