"""
Exporter: save ExtractResult to JSON and CSV files.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Union, Tuple

from .models import ExtractResult, CommentRecord, ReactionRecord


def _record_to_dict(record: Union[CommentRecord, ReactionRecord]) -> dict:
    return record.model_dump()


def save_json(result: ExtractResult, path: Union[str, Path]) -> Path:
    """
    Save the full extraction result as a JSON file.

    Returns the path to the written file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = result.model_dump()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return path


def save_csv(result: ExtractResult, path: Union[str, Path]) -> Tuple[Path, Path]:
    """
    Save comments and reactions as separate CSV files.

    Files are saved as:
      <path>_comments.csv
      <path>_reactions.csv

    Returns (comments_path, reactions_path).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Strip any extension from the stem so we can append our suffixes
    stem = path.parent / path.stem

    comments_path = Path(f"{stem}_comments.csv")
    reactions_path = Path(f"{stem}_reactions.csv")

    # Comments CSV
    comment_fields = [
        "type", "comment_id", "comment_type", "parent_comment_id",
        "author_name", "author_headline", "author_profile_url", "author_avatar",
        "comment_text", "comment_time_str", "is_edited", "is_pinned",
        "total_reactions", "total_replies", "post_url",
    ]
    _write_csv(comments_path, comment_fields, result.comments)

    # Reactions CSV
    reaction_fields = [
        "type", "reaction_type",
        "author_name", "author_headline", "author_profile_url", "author_avatar",
        "post_url",
    ]
    _write_csv(reactions_path, reaction_fields, result.reactions)

    return comments_path, reactions_path


def _write_csv(path: Path, fields: list[str], records: list) -> None:
    """Write records to a UTF-8-BOM CSV file (Excel-compatible)."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(_record_to_dict(record))


def save_all(result: ExtractResult, output_stem: Union[str, Path]) -> dict[str, Path]:
    """
    Save extraction results as both JSON and CSV.

    Args:
        result: The extraction result.
        output_stem: Base path/name without extension (e.g. "output/result").

    Returns:
        dict with keys 'json', 'comments_csv', 'reactions_csv' mapping to paths.
    """
    stem = Path(output_stem)

    json_path = save_json(result, stem.with_suffix(".json"))
    comments_csv, reactions_csv = save_csv(result, stem)

    return {
        "json": json_path,
        "comments_csv": comments_csv,
        "reactions_csv": reactions_csv,
    }
