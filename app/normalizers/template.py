
"""Day 17: TemplateNormalizer - one row per template."""

from typing import Any

from app.normalizers.base import Normalizer, parse_dt, safe_get


class TemplateNormalizer(Normalizer):
    table_name = "templates"

    def normalize(
        self,
        records: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Normalize DocuSign templates."""

        rows: list[dict[str, Any]] = []

        for raw in records:
            if not isinstance(raw, dict):
                continue

            template_id = safe_get(raw, "templateId")

            # Template ID is required for identification.
            if not template_id:
                continue

            rows.append({
                "template_id": str(template_id),
                "name": safe_get(raw, "name"),
                "created": parse_dt(
                    safe_get(raw, "created")
                ),
                "last_modified": parse_dt(
                    safe_get(raw, "lastModified")
                ),
                "owner_user_id": safe_get(
                    raw, "owner", "userId"
                ),
                "owner_name": safe_get(
                    raw, "owner", "userName"
                ),
                "owner_email": safe_get(
                    raw, "owner", "email"
                ),
                "shared": safe_get(raw, "shared"),
            })

        return {self.table_name: rows}
