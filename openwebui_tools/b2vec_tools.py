"""
title: B2Vec Company Database
description: Search and explore the B2Vec company database — semantic search, company details, similar companies, statistics, contact export, and SQL queries.
author: b2vec
version: 0.1.0
"""

import json
import requests
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        api_base_url: str = Field(
            default="http://web:8000",
            description="Base URL of the B2Vec Django API (internal Docker network)",
        )
        request_timeout: int = Field(
            default=30,
            description="HTTP request timeout in seconds",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _get(self, path: str, params: dict = None) -> dict:
        resp = requests.get(
            f"{self.valves.api_base_url}{path}",
            params=params,
            timeout=self.valves.request_timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: dict = None) -> dict:
        resp = requests.post(
            f"{self.valves.api_base_url}{path}",
            json=data,
            timeout=self.valves.request_timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def search_by_name(self, query: str, limit: int = 10) -> str:
        """
        Search companies by name or URL (text match).
        Use this when the user asks for a specific company by name or website.

        :param query: Company name or URL to search for.
        :param limit: Maximum number of results (default 10, max 50).
        :return: JSON with matching companies.
        """
        data = self._get("/api/text-search/", {"q": query, "n": min(limit, 50)})
        return json.dumps(data, ensure_ascii=False)

    def semantic_search(self, query: str, limit: int = 10) -> str:
        """
        Semantic search: find companies by description or concept.
        Use when the user describes what a company does rather than its name
        (e.g. "IT consulting", "renewable energy", "food production").

        :param query: Descriptive query about company activities or sector.
        :param limit: Maximum number of results (default 10, max 50).
        :return: JSON with companies ranked by semantic similarity.
        """
        data = self._get("/api/search/", {"q": query, "n": min(limit, 50)})
        return json.dumps(data, ensure_ascii=False)

    def get_company_details(self, company_id: str) -> str:
        """
        Get full details of a specific company by its ID token.
        Returns description, contacts, services, location, industry, size.

        :param company_id: The company ID token (from search results).
        :return: JSON with full company information.
        """
        data = self._get(f"/api/company-detail/{company_id}/")
        return json.dumps(data, ensure_ascii=False)

    def get_similar_companies(self, company_id: str, limit: int = 10) -> str:
        """
        Find companies similar to a given company using embedding similarity.
        Use when the user asks for alternatives, competitors, or similar companies.

        :param company_id: The company ID token (from search results).
        :param limit: Maximum number of similar companies (default 10, max 50).
        :return: JSON with similar companies and similarity scores.
        """
        data = self._get(f"/api/similar/{company_id}/", {"n": min(limit, 50)})
        return json.dumps(data, ensure_ascii=False)

    def get_database_stats(self) -> str:
        """
        Get database statistics: total companies, top industries, top cities,
        scraped/embedded counts. Use for overview questions about the database.

        :return: JSON with database statistics.
        """
        data = self._get("/api/stats/")
        return json.dumps(data, ensure_ascii=False)

    def run_sql_query(self, query: str) -> str:
        """
        Execute a read-only SQL SELECT query on the company database.
        Use for precise quantitative questions (counts, aggregations, filters).
        Max 50 rows returned.

        Schema:
        - core_company (id, handle, name, url, website, industry, size, type, founded, city, state, country_code)
        - core_companyproperties (company_id, phone, email, vat_number, address, description, services JSONB, linkedin)
        - core_companyembedding (company_id, umap_x, umap_y, cluster_id, cluster_label)
        - core_scrapeddata (company_id, text_content, cleaned_content)

        The "size" field contains text ranges: '11-50', '51-200', '201-500', '501-1000', '1001-5000', '5001-10000', '10001+'.

        :param query: SQL SELECT query to execute.
        :return: JSON with query results.
        """
        data = self._post("/api/sql/", {"query": query})
        return json.dumps(data, ensure_ascii=False)
