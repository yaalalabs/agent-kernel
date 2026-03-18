import asyncio
import atexit
import json
import os
import re
from typing import List

from neo4j import GraphDatabase

from base import AbstractKnowledgeBase

#from openai_model import model


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


class Neo4jManager(AbstractKnowledgeBase):
    def __init__(self):
        self.driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
        )
        self.driver.verify_connectivity()

    def close(self):
        self.driver.close()

    def clear(self) -> None:
        self.driver.execute_query("MATCH (n) DETACH DELETE n", database_=NEO4J_DATABASE)

    def _validate_identifier(self, value: str, field_name: str) -> str:
        if not value or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError(
                f"Invalid {field_name}: '{value}'. Use letters, numbers, and underscore only, "
                "and do not start with a number."
            )
        return value

    def add(
        self,
        label_a: str,
        props_a: dict,
        relationship: str,
        label_b: str,
        props_b: dict,
        rel_props: dict = None,
    ) -> None:
        label_a = self._validate_identifier(label_a, "label_a")
        label_b = self._validate_identifier(label_b, "label_b")
        relationship = self._validate_identifier(relationship, "relationship")

        if not props_a or "name" not in props_a:
            raise ValueError("props_a must include a 'name' field.")
        if not props_b or "name" not in props_b:
            raise ValueError("props_b must include a 'name' field.")

        query = f"""
        MERGE (a:{label_a} {{name: $a_name}})
        SET a += $props_a
        MERGE (b:{label_b} {{name: $b_name}})
        SET b += $props_b
        MERGE (a)-[r:{relationship}]->(b)
        SET r += $rel_props
        RETURN a, r, b
        """

        self.driver.execute_query(
            query,
            a_name=props_a["name"],
            props_a=props_a,
            b_name=props_b["name"],
            props_b=props_b,
            rel_props=rel_props or {},
            database_=NEO4J_DATABASE,
        )

    def add_records(self, records, **kwargs) -> None:
        for record in records:
            relationship = record.get("relationship") or record.get("relation")
            if not relationship:
                raise ValueError("Each record must include 'relationship' (or legacy 'relation').")

            self.add(
                label_a=record["label_a"],
                props_a=record["props_a"],
                relationship=relationship,
                label_b=record["label_b"],
                props_b=record["props_b"],
                rel_props=record.get("rel_props", {}),
            )

    def _extract_search_terms(self, text: str) -> List[str]:
        terms = re.findall(r"[A-Za-z0-9_]+", (text or "").lower())
        return [term for term in terms if len(term) > 1]

    def _format_graph_record(self, record) -> str:
        rel_props = record["rel_props"] or {}

        if not rel_props:
            return f"{record['source']} -[{record['rel']}]-> {record['target']}"

        prop_str = ", ".join(f"{k}:{v}" for k, v in rel_props.items())
        return f"{record['source']} -[{record['rel']} {{{prop_str}}}]-> {record['target']}"

    def search(self, query: str, **kwargs):
        limit = kwargs.get("limit", 10)

        terms = self._extract_search_terms(query)
        if not terms:
            return []

        query = """
        MATCH (source)-[rel]->(target)
        WHERE any(term IN $terms WHERE
            toLower(coalesce(source.name, "")) CONTAINS term
            OR toLower(coalesce(target.name, "")) CONTAINS term
        )
        RETURN source.name AS source,
               type(rel) AS rel,
               properties(rel) AS rel_props,
               target.name AS target
        LIMIT $limit
        """

        records, summary, keys = self.driver.execute_query(
            query,
            terms=terms,
            limit=limit,
            database_=NEO4J_DATABASE,
        )

        _ = summary
        _ = keys

        lines = [self._format_graph_record(record) for record in records]
        return list(dict.fromkeys(lines))

    def search_records(self, query: str, limit: int = 3, **kwargs):
        return [{"text": line, "metadata": {}} for line in self.search(query, limit=limit)]


graph_manager = Neo4jManager()
atexit.register(graph_manager.close)


def load_graph_kb_impl(triples):
    try:
        graph_manager.add_records(triples)
        return f"Loaded {len(triples)} triples into graph."
    except Exception as e:
        return f"Failed loading graph data: {e}"


def query_graph_kb_impl(entity):
    try:
        results = graph_manager.search(entity)
        if not results:
            return f"No facts found for '{entity}'"
        return "\n".join(results)
    except Exception as e:
        return f"Graph query failed: {e}"


