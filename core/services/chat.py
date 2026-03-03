import csv
import io
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

import requests as http_requests
from django.conf import settings
from django.db.models import Count, Q, Value, IntegerField, Case, When

from core.models import Company, ScrapedData, CompanyEmbedding, CompanyProperties
from core.id_cipher import encode_id

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = """\
Sei un assistente esperto del database aziendale B2Vec. \
Il database contiene aziende italiane ed europee con informazioni su industria, \
dimensione, località, servizi, descrizione e embedding semantici.

REGOLA FONDAMENTALE: LEGGI ATTENTAMENTE i risultati JSON restituiti dai tool. \
Basa la tua risposta SOLO sui dati reali presenti nei risultati. \
NON inventare mai nomi di aziende, dati o dettagli che non compaiono nei risultati. \
I risultati vengono mostrati all'utente come schede grafiche, quindi nella tua risposta \
fornisci solo un breve commento basato sui NOMI e INDUSTRIE reali che vedi nei risultati.

STRATEGIA DI RICERCA — se un tool restituisce 0 risultati o risultati non pertinenti, NON arrenderti:
- Se search_by_name fallisce, estrai il dominio dall'URL (es. "hackability" da "https://hackability.it") e riprova, oppure usa semantic_search.
- Se semantic_search dà risultati non pertinenti (es. cerchi formaggi ma trovi consulenza), dillo e prova varianti o web_search.
- Se l'utente fornisce un URL, cerca anche per dominio/nome del sito.
- Usa web_search per cercare su internet informazioni non presenti nel database.
- Puoi chiamare più tool in sequenza fino a trovare una risposta soddisfacente.

CONTATTI: quando l'utente chiede email, telefoni o contatti di aziende per settore/attività, \
usa semantic_search con include_contacts=true. Questo restituisce email, telefono e descrizione per ogni risultato.

EXPORT: quando l'utente vuole esportare, scaricare o ottenere un file con una lista di contatti/email/telefoni, \
usa export_contacts. Questo genera un file CSV scaricabile con i contatti delle aziende trovate per similarità semantica.

SQL: usa run_sql per domande quantitative precise (conteggi, aggregazioni, filtri specifici). \
Il campo "size" contiene range testuali come '11-50', '51-200', '201-500', '501-1000', '1001-5000', '5001-10000', '10001+'.

Rispondi in italiano se l'utente scrive in italiano, altrimenti in inglese."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_by_name",
            "description": "Search companies by name or URL (text match). Use for finding specific companies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Company name or URL to search for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 10)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": "Semantic search: find companies by description/concept (e.g. 'consulenza IT', 'fintech', 'energia rinnovabile'). Use when the user describes what a company does rather than its name. Set include_contacts=true to also return email, phone and description for each result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Descriptive query about company activities or sector",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 10)",
                    },
                    "include_contacts": {
                        "type": "boolean",
                        "description": "If true, include email, phone and description from company properties (default false)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company",
            "description": "Get full details of a specific company by name (exact or partial match). Returns all available info: description, contacts, services, location, industry, size.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Company name to look up",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_similar",
            "description": "Find companies similar to a given company using embedding similarity. Use when user asks for alternatives, competitors, or similar companies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the reference company",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 10)",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stats",
            "description": "Get database statistics: total companies, industries breakdown, top cities, scraped/embedded counts. Use for overview questions.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the internet via DuckDuckGo. Use when the database doesn't have the information needed, or to find details about a company/topic not in the local DB.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_contacts",
            "description": "Export contacts (email, phone) of companies matching a semantic query. Generates a downloadable CSV file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Descriptive query about company activities or sector",
                    },
                    "min_similarity": {
                        "type": "integer",
                        "description": "Minimum similarity percentage (0-100, default 60)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max companies to include (default 200)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": (
                "Execute a read-only SQL SELECT query on the PostgreSQL database. "
                "Use for precise/aggregate questions (counts, filters, GROUP BY, JOINs). Max 50 rows.\n\n"
                "Schema:\n"
                "- core_company (id, handle, name, url, website, industry, size, type, founded, city, state, country_code, scrape_status, created_at)\n"
                "- core_scrapeddata (id, company_id FK→core_company, text_content, cleaned_content, scraped_at)\n"
                "- core_companyembedding (id, company_id FK→core_company, umap_x, umap_y, cluster_id, cluster_label, created_at)\n"
                "- core_companyproperties (id, company_id FK→core_company, phone, email, vat_number, address, description, services JSONB, linkedin, facebook, instagram, extracted_at, created_at)"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL SELECT query to execute",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


# --- Tool executor functions ---

def _exec_search_by_name(query: str, limit: int = 10) -> dict:
    limit = max(1, min(limit, 30))
    results = (
        Company.objects
        .filter(
            Q(name__icontains=query) |
            Q(url__icontains=query) |
            Q(website__icontains=query)
        )
        .annotate(
            rank=Case(
                When(name__iexact=query, then=Value(0)),
                When(name__istartswith=query, then=Value(1)),
                When(name__icontains=query, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        )
        .order_by('rank', 'name')[:limit]
    )
    companies = [
        {
            "name": c.name,
            "website": c.website or "",
            "industry": c.industry or "N/A",
            "city": c.city or "N/A",
            "country": c.country_code or "N/A",
            "link": f"/company/{encode_id(c.id)}/",
        }
        for c in results
    ]
    return {"count": len(companies), "results": companies}


def _exec_semantic_search(query: str, limit: int = 10, include_contacts: bool = False) -> dict:
    from pgvector.django import CosineDistance

    limit = max(1, min(limit, 30))

    resp = http_requests.post(
        f"{settings.OLLAMA_BASE_URL}/api/embed",
        json={"model": settings.OLLAMA_EMBED_MODEL, "input": query},
        timeout=30,
    )
    resp.raise_for_status()
    query_vector = resp.json()["embeddings"][0]

    results = (
        CompanyEmbedding.objects
        .annotate(distance=CosineDistance('vector', query_vector))
        .order_by('distance')
        .select_related('company')[:limit]
    )

    # Prefetch properties if contacts requested
    if include_contacts:
        company_ids = [emb.company_id for emb in results]
        props_map = {
            p.company_id: p
            for p in CompanyProperties.objects.filter(company_id__in=company_ids)
        }

    companies = []
    for emb in results:
        entry = {
            "name": emb.company.name,
            "website": emb.company.website or "",
            "industry": emb.company.industry or "N/A",
            "city": emb.company.city or "N/A",
            "similarity": f"{(1 - emb.distance) * 100:.1f}%",
            "link": f"/company/{encode_id(emb.company.id)}/",
        }
        if include_contacts:
            props = props_map.get(emb.company_id)
            entry["email"] = (props.email if props and props.email else None)
            entry["phone"] = (props.phone if props and props.phone else None)
            entry["description"] = (props.description if props and props.description else None)
        companies.append(entry)

    return {"query": query, "count": len(companies), "results": companies}


def _exec_get_company(name: str) -> dict:
    company = (
        Company.objects
        .filter(name__icontains=name)
        .annotate(
            rank=Case(
                When(name__iexact=name, then=Value(0)),
                When(name__istartswith=name, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by('rank')
        .first()
    )
    if not company:
        return {"error": f"No company found matching '{name}'"}

    props = getattr(company, 'properties', None)
    embedding = getattr(company, 'embedding', None)

    data = {
        "name": company.name,
        "url": company.url,
        "website": company.website,
        "industry": company.industry,
        "size": company.size,
        "type": company.type,
        "founded": company.founded,
        "city": company.city,
        "state": company.state,
        "country": company.country_code,
        "link": f"/company/{encode_id(company.id)}/",
    }
    if props:
        data["description"] = props.description
        data["phone"] = props.phone
        data["email"] = props.email
        data["vat_number"] = props.vat_number
        data["address"] = props.address
        data["services"] = props.services
        data["linkedin"] = props.linkedin
    if embedding:
        data["cluster"] = embedding.cluster_label

    return data


def _exec_get_similar(name: str, limit: int = 10) -> dict:
    from pgvector.django import CosineDistance

    limit = max(1, min(limit, 30))

    company = Company.objects.filter(name__icontains=name).first()
    if not company:
        return {"error": f"No company found matching '{name}'"}

    try:
        target = company.embedding
    except CompanyEmbedding.DoesNotExist:
        return {"error": f"No embedding available for '{company.name}'"}

    results = (
        CompanyEmbedding.objects
        .exclude(company_id=company.id)
        .annotate(distance=CosineDistance('vector', target.vector))
        .order_by('distance')
        .select_related('company')[:limit]
    )
    similar = [
        {
            "name": emb.company.name,
            "website": emb.company.website or "",
            "industry": emb.company.industry or "N/A",
            "city": emb.company.city or "N/A",
            "similarity": f"{(1 - emb.distance) * 100:.1f}%",
            "link": f"/company/{encode_id(emb.company.id)}/",
        }
        for emb in results
    ]
    return {"reference": company.name, "count": len(similar), "similar": similar}


def _exec_get_stats() -> dict:
    total = Company.objects.count()
    scraped = ScrapedData.objects.count()
    embedded = CompanyEmbedding.objects.count()
    with_properties = CompanyProperties.objects.count()

    top_industries = list(
        Company.objects
        .filter(industry__isnull=False)
        .exclude(industry='')
        .values('industry')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )
    top_cities = list(
        Company.objects
        .filter(city__isnull=False)
        .exclude(city='')
        .values('city')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )

    return {
        "total_companies": total,
        "scraped": scraped,
        "with_embeddings": embedded,
        "with_properties": with_properties,
        "top_industries": top_industries,
        "top_cities": top_cities,
    }


def _exec_web_search(query: str, limit: int = 5) -> dict:
    """Search DuckDuckGo and return results."""
    try:
        resp = http_requests.get(
            'https://html.duckduckgo.com/html/',
            params={'q': query},
            headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0'},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        return {"error": f"Ricerca web fallita: {e}"}

    html = resp.text
    links = re.findall(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)

    results = []
    for i, (raw_url, title) in enumerate(links[:limit]):
        # Extract real URL from DDG redirect
        m = re.search(r'uddg=([^&]+)', raw_url)
        url = unquote(m.group(1)) if m else raw_url
        title = re.sub(r'<[^>]+>', '', title).strip()
        snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ''
        if title:
            results.append({"title": title, "url": url, "snippet": snippet})

    return {"query": query, "count": len(results), "results": results}


_FORBIDDEN_SQL = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY)\b',
    re.IGNORECASE,
)


def _exec_run_sql(query: str) -> dict:
    normalized = ' '.join(query.split())
    if not normalized.lstrip('( ').upper().startswith('SELECT'):
        return {"error": "Solo query SELECT sono permesse."}

    if _FORBIDDEN_SQL.search(normalized):
        return {"error": "La query contiene keyword non permesse."}

    if 'LIMIT' not in normalized.upper():
        query = normalized.rstrip(';') + ' LIMIT 50'

    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            if cursor.description is None:
                return {"error": "La query non ha restituito colonne."}
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchmany(50)
        results = [dict(zip(columns, row)) for row in rows]
        return {"columns": columns, "row_count": len(results), "results": results}
    except Exception as e:
        return {"error": f"Errore SQL: {e}"}


def _exec_export_contacts(query: str, min_similarity: int = 60, limit: int = 200) -> dict:
    from pgvector.django import CosineDistance

    limit = max(1, min(limit, 500))
    min_similarity = max(0, min(min_similarity, 100))
    threshold = 1 - (min_similarity / 100)

    resp = http_requests.post(
        f"{settings.OLLAMA_BASE_URL}/api/embed",
        json={"model": settings.OLLAMA_EMBED_MODEL, "input": query},
        timeout=30,
    )
    resp.raise_for_status()
    query_vector = resp.json()["embeddings"][0]

    results = (
        CompanyEmbedding.objects
        .annotate(distance=CosineDistance('vector', query_vector))
        .filter(distance__lte=threshold)
        .order_by('distance')
        .select_related('company')[:limit]
    )

    company_ids = [emb.company_id for emb in results]
    props_map = {
        p.company_id: p
        for p in CompanyProperties.objects.filter(company_id__in=company_ids)
    }

    # Generate CSV
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['name', 'website', 'industry', 'city', 'email', 'phone', 'similarity'])

    with_email = 0
    with_phone = 0
    for emb in results:
        props = props_map.get(emb.company_id)
        email = (props.email if props and props.email else '')
        phone = (props.phone if props and props.phone else '')
        if email:
            with_email += 1
        if phone:
            with_phone += 1
        similarity = round((1 - emb.distance) * 100, 1)
        writer.writerow([
            emb.company.name,
            emb.company.website or '',
            emb.company.industry or '',
            emb.company.city or '',
            email,
            phone,
            f"{similarity}%",
        ])

    # Save to exports/ directory
    exports_dir = Path(settings.BASE_DIR) / 'exports'
    exports_dir.mkdir(exist_ok=True)

    # Cleanup old files (>1 hour)
    now = time.time()
    for f in exports_dir.iterdir():
        if f.is_file() and (now - f.stat().st_mtime) > 3600:
            f.unlink(missing_ok=True)

    filename = f"export_{uuid4().hex[:12]}.csv"
    filepath = exports_dir / filename
    filepath.write_text(buf.getvalue(), encoding='utf-8')

    return {
        "query": query,
        "count": len(company_ids),
        "with_email": with_email,
        "with_phone": with_phone,
        "download_url": f"/exports/{filename}",
    }


TOOL_EXECUTORS = {
    "search_by_name": lambda args: _exec_search_by_name(args["query"], args.get("limit", 10)),
    "semantic_search": lambda args: _exec_semantic_search(args["query"], args.get("limit", 10), args.get("include_contacts", False)),
    "get_company": lambda args: _exec_get_company(args["name"]),
    "get_similar": lambda args: _exec_get_similar(args["name"], args.get("limit", 10)),
    "get_stats": lambda args: _exec_get_stats(),
    "web_search": lambda args: _exec_web_search(args["query"], args.get("limit", 5)),
    "export_contacts": lambda args: _exec_export_contacts(args["query"], args.get("min_similarity", 60), args.get("limit", 200)),
    "run_sql": lambda args: _exec_run_sql(args["query"]),
}


def execute_tool(name: str, arguments: dict) -> str:
    executor = TOOL_EXECUTORS.get(name)
    if not executor:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = executor(arguments)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        logger.exception(f"Tool {name} failed")
        return json.dumps({"error": f"Tool execution failed: {str(e)}"})


def chat_stream(messages: list[dict]):
    """Generator yielding (event_type, data) tuples. Streams the final response token-by-token."""
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    for _round in range(MAX_TOOL_ROUNDS):
        # Non-streaming call to detect tool_calls
        resp = http_requests.post(
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": settings.OLLAMA_CHAT_MODEL,
                "messages": full_messages,
                "tools": TOOLS,
                "stream": False,
            },
            timeout=120,
        )
        resp.raise_for_status()
        assistant_msg = resp.json().get("message", {})
        tool_calls = assistant_msg.get("tool_calls")

        if not tool_calls:
            # No tools — re-call with streaming for token-by-token output
            stream_resp = http_requests.post(
                f"{settings.OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": settings.OLLAMA_CHAT_MODEL,
                    "messages": full_messages,
                    "tools": TOOLS,
                    "stream": True,
                },
                stream=True,
                timeout=120,
            )
            stream_resp.raise_for_status()
            for line in stream_resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                token = chunk.get("message", {}).get("content", "")
                if token:
                    yield ("token", token)
            yield ("done", "")
            return

        # Tool round — execute tools and loop
        full_messages.append(assistant_msg)
        for tc in tool_calls:
            fn = tc["function"]
            tool_name = fn["name"]
            tool_args = fn.get("arguments", {})
            logger.info(f"Tool call: {tool_name}({tool_args})")

            yield ("tool_call", {"tool": tool_name, "args": tool_args})

            result_str = execute_tool(tool_name, tool_args)
            try:
                result_data = json.loads(result_str)
            except json.JSONDecodeError:
                result_data = {"raw": result_str}

            yield ("tool_result", {"tool": tool_name, "data": result_data})
            full_messages.append({"role": "tool", "content": result_str})

    # Exhausted rounds
    yield ("token", "Mi dispiace, non sono riuscito a completare la ricerca. Riprova con una domanda più semplice.")
    yield ("done", "")
