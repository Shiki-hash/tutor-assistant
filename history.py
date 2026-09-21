"""Read immutable generations/reviews as issue timelines; no migration required."""
import re
from pathlib import Path
from app import read_json, UserFacingError

RUN_ID = re.compile(r'\d{8}-\d{6}-[0-9a-f]{8}')


def checked_id(value):
    if not isinstance(value, str) or not RUN_ID.fullmatch(value):
        raise UserFacingError('问题编号无效。')
    return value


def all_runs(root):
    records = []
    for path in root.glob('*/result.json'):
        if not RUN_ID.fullmatch(path.parent.name):
            continue
        try:
            record = read_json(path)
            if not isinstance(record.get('input'), dict) or not isinstance(record.get('draft'), dict):
                continue
            reviews = []
            for review_path in path.parent.glob('review-*.json'):
                try:
                    review = read_json(review_path)
                    if all(k in review for k in ('saved_at', 'reply', 'status', 'note')):
                        reviews.append(dict(review, file=review_path.name))
                except (ValueError, OSError, TypeError):
                    continue
            reviews.sort(key=lambda r: (r['saved_at'], r['file']))
            records.append(dict(run_id=path.parent.name, record=record, reviews=reviews))
        except (ValueError, OSError, TypeError):
            continue
    return sorted(records, key=lambda r: (r['record'].get('created_at', ''), r['run_id']))


def issue_id(run):
    return run['record'].get('issue_id', run['run_id'])


def detail(root, identifier):
    checked_id(identifier)
    versions = [r for r in all_runs(root) if issue_id(r) == identifier]
    if not versions:
        raise UserFacingError('找不到这条问题记录，请刷新列表。')
    latest = versions[-1]
    review = latest['reviews'][-1] if latest['reviews'] else None
    revision = latest['run_id'] + ':' + (review['file'] if review else '')
    return dict(issue_id=identifier, versions=versions, revision=revision)


def summaries(root):
    grouped = {}
    for run in all_runs(root):
        grouped.setdefault(issue_id(run), []).append(run)
    result = []
    for identifier, versions in grouped.items():
        first, last = versions[0], versions[-1]
        record = last['record']
        review = last['reviews'][-1] if last['reviews'] else None
        result.append(dict(issue_id=identifier, message=first['record']['input'].get('message', ''),
                           case_id=record.get('case_id'), created_at=first['record'].get('created_at', ''),
                           updated_at=review['saved_at'] if review else record.get('created_at', ''),
                           status=review['status'] if review else '待审核', versions=len(versions),
                           synthetic=first['record'].get('synthetic_input', True)))
    return sorted(result, key=lambda x: x['updated_at'], reverse=True)
