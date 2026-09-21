"""Versioned natural-language query planning using PostgreSQL's Portuguese dictionary."""

LEXICAL_REVISION = "lexical-v2"

# The first sixteen distinct normalized lexemes retain input order, with stable ties.
# quote_literal protects tsquery syntax; user operators are treated as ordinary text.
LEXEME_PLAN_SQL = """
SELECT coalesce(string_agg(quote_literal(term), ' | ' ORDER BY first_position,term),'')
FROM (
    SELECT term,min(parsed.ordinality) AS first_position
    FROM ts_debug('portuguese',CAST(:query AS text)) WITH ORDINALITY AS parsed
    CROSS JOIN LATERAL unnest(parsed.lexemes) AS term
    GROUP BY term
    ORDER BY first_position,term
    LIMIT 16
) AS bounded_terms
"""
