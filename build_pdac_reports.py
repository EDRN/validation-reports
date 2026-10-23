#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import re
from urllib.parse import quote

import pandas as pd

REQUIRED_COLUMNS = [
    'Site ID',
    'File Path',
    'Study Instance UID',
    'Series Instance UID',
    'Profile',
    'Score',
    'Findings',
    'Details',
]

PHI_FINDINGS = [
    '🖼️ Possible Burned-in PHI/PII (Pixels)',
    '🙈 Possible PHI/PII in Header',
]

VALIDATION_FINDINGS = [
    '⚠️ Missing Required Tags',
    '❌ Error',
    '👮 Warning',
]

def categorize_finding(raw: str) -> str:
    text = (raw or '').strip()
    if not text:
        return 'Other'
    lowered = text.lower()

    if 'error' in lowered or '❌' in text:
        return 'Critical Errors'
    if 'missing' in lowered or '⚠️' in text:
        return 'Missing Required Tags'
    if 'warning' in lowered or '👮' in text:
        return 'Warnings'
    if 'header' in lowered or '🙈' in text:
        return 'PHI in Header'
    if 'pixel' in lowered or '🖼️' in text or 'burned-in' in lowered:
        return 'Burned-in PHI (Pixels)'
    return 'Other'


def extract_tag_name(details: str) -> str:
    text = (details or '').strip()
    if not text:
        return ''

    match = re.search(r'\(([0-9A-Fa-f]{4},[0-9A-Fa-f]{4})\)\s*\(?([A-Za-z0-9_]+)\)?', text)
    if match:
        return match.group(2)

    for pat in [
        r'Missing tag:\s*([A-Za-z0-9_\-]+)',
        r'High-risk tag:\s*([A-Za-z0-9_\-]+)',
        r'Detected pattern:\s*([A-Za-z0-9_\-]+)',
    ]:
        m = re.search(pat, text)
        if m:
            return m.group(1)

    return ''


def _clean(text: str) -> str:
    if not isinstance(text, str):
        return ''
    return text.strip()


def to_site_filename(file_path: str) -> str:
    text = _clean(file_path)
    if not text:
        return ''
    return Path(text).name


def to_labcas_filename(site_filename: str) -> str:
    # For PDAC, LabCAS keeps the uploaded filename as-is.
    return _clean(site_filename)


def build_labcas_url(file_path: str) -> str:
    raw = _clean(file_path)
    if not raw:
        return ''

    # Build URL from the LabCAS archive root plus the file path suffix
    # that starts with "Pre-diagnostic".
    marker = 'Pre-diagnostic'
    marker_idx = raw.find(marker)
    if marker_idx >= 0:
        relative = raw[marker_idx:]
    else:
        prefix = '/labcas-data/labcas-backend/archive/edrn/'
        relative = raw[len(prefix):] if raw.startswith(prefix) else raw.lstrip('/')

    encoded = quote(relative, safe='/')
    return f'https://edrn-labcas.jpl.nasa.gov/labcas-ui/f/index.html?file_id={encoded}'


def extract_series_uid(details: str, fallback_series_uid: str) -> str:
    text = _clean(details)
    match = re.search(
        r'(?:Series\s*Instance\s*UID|SeriesInstanceUID)\s*[:=]\s*([0-9]+(?:\.[0-9]+)+)',
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return _clean(fallback_series_uid)


def extract_affected_tags(details: str, validation_issue: str) -> str:
    tags = []
    for tag_group, tag_name in re.findall(r'\(([0-9A-Fa-f]{4},[0-9A-Fa-f]{4})\)\s*\(?([A-Za-z0-9_]+)\)?', _clean(details)):
        tags.append(f'({tag_group}) {tag_name}')

    issue = _clean(validation_issue)
    issue_match = re.search(r'^(?:Missing tag|Invalid format):\s*([A-Za-z0-9_]+)', issue)
    if issue_match:
        issue_tag = issue_match.group(1)
        if not any(issue_tag in t for t in tags):
            tags.append(issue_tag)

    unique_tags = []
    seen = set()
    for tag in tags:
        if tag and tag not in seen:
            seen.add(tag)
            unique_tags.append(tag)
    return '; '.join(unique_tags)


def details_summary(findings: str, validation_issue: str, affected_tags: str, count: int) -> str:
    issue = _clean(validation_issue)
    if issue.startswith('Missing tag:') and affected_tags:
        return f'{issue} appears across {count} file(s) in this Study/Series. Affected tag(s): {affected_tags}.'
    if issue.startswith('Invalid format:'):
        return f'{issue} appears across {count} file(s) in this Study/Series.'
    if _clean(findings) == '❌ Error':
        return f'{issue} appears across {count} file(s) in this Study/Series.'
    return f'{issue} appears across {count} file(s) in this Study/Series.'


def recommended_action(validation_issue: str, findings: str) -> str:
    issue = _clean(validation_issue)
    if issue.startswith('Missing tag:'):
        return 'Site review requested: confirm whether metadata can be corrected or should be documented as unavailable for legacy data.'
    if issue.startswith('Invalid format:'):
        return 'Correct and re-upload if metadata can be restored.'
    if _clean(findings) == '❌ Error':
        return 'Validation rule review if the site believes the finding is incorrect or not applicable.'
    return 'Site review requested: confirm issue and respond with resolution or rationale.'


def parse_phi_field_and_value(validation_issue: str, details: str, finding: str) -> tuple[str, str]:
    issue = _clean(validation_issue)
    text = _clean(details)

    if issue.startswith('High-risk tag:'):
        field_match = re.search(r'^High-risk tag:\s*([^;]+)', issue)
        field = _clean(field_match.group(1)) if field_match else ''
        value_match = re.search(r'Detected pattern:\s*([A-Za-z0-9_\-]+)', issue)
        if value_match:
            return field, value_match.group(1)
        quoted_match = re.search(r'«([^»]+)»', text)
        return field, quoted_match.group(1) if quoted_match else ''

    if issue.startswith('Detected pattern:'):
        value_match = re.search(r'Detected pattern:\s*([A-Za-z0-9_\-]+)', issue)
        value = value_match.group(1) if value_match else ''
        field = 'Burned-in Pixels' if _clean(finding) == '🖼️ Possible Burned-in PHI/PII (Pixels)' else 'PHI Pattern'
        return field, value

    quoted_match = re.search(r'«([^»]+)»', text)
    return issue, quoted_match.group(1) if quoted_match else ''


def extract_detected_actual_value(details: str) -> str:
    text = _clean(details)
    if not text:
        return ''

    # Most raw rows include the detected value wrapped in guillemets.
    quoted = re.search(r'«([^»]+)»', text)
    if quoted:
        return _clean(quoted.group(1))

    # Fallback for plain quoted values.
    plain_quoted = re.search(r'"([^"]+)"', text)
    if plain_quoted:
        return _clean(plain_quoted.group(1))

    return ''


def combine_pattern_and_actual(pattern_value: str, actual_value: str) -> str:
    pattern = _clean(pattern_value)
    actual = _clean(actual_value)
    if pattern and actual and pattern != actual:
        return f'{pattern}: {actual}'
    if actual:
        return actual
    return pattern


def summarize_issue(details: str, finding: str) -> tuple[str, str]:
    text = _clean(details)
    if not text:
        return '', ''

    def extract_tag(source: str) -> str:
        match = re.search(
            r'Required tag not found in DICOM dataset:\s*\((?:[0-9A-Fa-f]{4},[0-9A-Fa-f]{4})\)\s*\(?([A-Za-z0-9_]+)\)?',
            source,
        )
        if match:
            return match.group(1)
        match = re.search(r'\((?:[0-9A-Fa-f]{4},[0-9A-Fa-f]{4})\)\s*\(([A-Za-z0-9_]+)\)', source)
        if match:
            return match.group(1)
        match = re.search(r'High-risk tag: ([A-Za-z0-9_]+)', source)
        if match:
            return match.group(1)
        return source

    def trim_boilerplate(value: str) -> str:
        value = value.strip()
        value = value.replace(' — please review for completeness and format', '')
        value = value.replace(', please review for completeness and format', '')
        return value

    if finding == '🖼️ Possible Burned-in PHI/PII (Pixels)':
        match = re.search(r'Detected with pattern ([A-Za-z0-9_]+)', text)
        pattern = match.group(1) if match else text
        return pattern, f'Detected pattern: {pattern}'

    if finding == '🙈 Possible PHI/PII in Header':
        # Prefer full path exactly as shown in Details (e.g., OriginalAttributesSequence[0].PatientID).
        path_match = re.search(r'path\s+"{1,2}([^"\r\n]+)"{1,2}', text)
        tag = _clean(path_match.group(1)) if path_match else ''

        # Fallback to explicit high-risk tag phrases.
        if not tag:
            tag_match = re.search(r'Strict high-risk tag\s+"{1,2}([^"\r\n]+)"{1,2}', text)
            if not tag_match:
                tag_match = re.search(r'High-risk tag:\s*([^;]+)', text)
            tag = _clean(tag_match.group(1)) if tag_match else ''

        # Final fallback to explicit DICOM tag text when present, e.g. (0010,0020) (PatientID).
        if not tag:
            dicom_tag_match = re.search(r'\([0-9A-Fa-f]{4},[0-9A-Fa-f]{4}\)\s*\(([A-Za-z0-9_]+)\)', text)
            tag = _clean(dicom_tag_match.group(1)) if dicom_tag_match else ''

        if not tag:
            tag = text

        pattern_match = re.search(r'Using pattern ([A-Za-z0-9_]+)', text)
        if not pattern_match:
            pattern_match = re.search(r'Detected pattern ([A-Za-z0-9_]+)', text)

        pattern = pattern_match.group(1) if pattern_match else ''
        if pattern:
            return tag, f'High-risk tag: {tag}; Detected pattern: {pattern}'
        return tag, f'High-risk tag: {tag}'

    if finding in {'⚠️ Missing Required Tags', '👮 Warning'}:
        lowered = text.lower()
        if any(marker in lowered for marker in ['tag missing', 'required tag not found', 'missing a value', 'must be present']):
            tag = extract_tag(text)
            return tag, f'Missing tag: {tag}'

        if 'does not match expected pattern' in lowered or 'must not be numeric-only' in lowered or 'cannot have leading or trailing spaces' in lowered:
            match = re.search(r'Value for tag does not match expected pattern:\s*([A-Za-z0-9_]+)\s*(.*)$', text)
            if match:
                tag = match.group(1)
                reason = trim_boilerplate(match.group(2))
                value = f'{tag} {reason}'.strip()
                return tag, f'Invalid format: {value}'
            tag = extract_tag(text)
            return tag, f'Invalid format: {tag}'

        if 'windowcenter' in lowered or 'windowwidth' in lowered:
            tag = 'WindowCenter' if 'windowcenter' in lowered else 'WindowWidth'
            return tag, f'Missing tag: {tag}'

        return text, text

    if finding == '❌ Error':
        return text, f'Error: {text}'

    return text, text


def build_phi_reports(all_rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    subset = all_rows[all_rows['Findings'].isin(PHI_FINDINGS)].copy()
    subset['File Name (sent by site)'] = subset['File Path'].map(to_site_filename)
    subset['Example File Path'] = subset['File Path'].map(
        lambda path: str(Path(_clean(path)).parent) if _clean(path) else ''
    )
    issue_pairs = subset.apply(lambda r: summarize_issue(r['Details'], r['Findings']), axis=1)
    subset['Validation Issue'] = issue_pairs.apply(lambda pair: pair[1])
    subset['Series Instance UID'] = subset.apply(
        lambda r: extract_series_uid(r['Details'], r.get('Series Instance UID', '')),
        axis=1,
    )
    phi_parsed = subset.apply(
        lambda r: parse_phi_field_and_value(r['Validation Issue'], r['Details'], r['Findings']),
        axis=1,
    )
    subset['DICOM Tag / Field'] = phi_parsed.apply(lambda pair: pair[0])
    subset['Detected Value'] = phi_parsed.apply(lambda pair: pair[1])
    subset['Detected Actual Value'] = subset['Details'].map(extract_detected_actual_value)
    subset['Detected Value'] = subset.apply(
        lambda r: combine_pattern_and_actual(r['Detected Value'], r['Detected Actual Value']),
        axis=1,
    )

    detail = subset.copy()
    detail['Reconciliation Status'] = 'Needs PHI reconciliation'
    detail['Action'] = 'Review each affected file and reconcile exact detected value.'
    detail = detail[
        [
            'Site ID',
            'Study Instance UID',
            'Series Instance UID',
            'File Name (sent by site)',
            'File Path',
            'Findings',
            'Validation Issue',
            'DICOM Tag / Field',
            'Detected Value',
            'Details',
            'Reconciliation Status',
            'Action',
        ]
    ].drop_duplicates()
    detail = detail.sort_values(
        by=['Site ID', 'Study Instance UID', 'Series Instance UID', 'Validation Issue', 'File Name (sent by site)'],
        na_position='last',
    )

    group_cols = [
        'Site ID',
        'PatientID',
        'Study Instance UID',
        'Findings',
        'DICOM Tag / Field',
        'Detected Value',
        'Validation Issue',
    ]
    summary = subset.groupby(group_cols, dropna=False).agg(
        **{
            'Affected File Count': ('File Name (sent by site)', 'nunique'),
            'Example File Name (sent by site)': ('File Name (sent by site)', 'first'),
            'Example File Path': ('Example File Path', 'first'),
        }
    ).reset_index()
    if summary.empty:
        summary['Details Summary'] = ''
    else:
        summary['Details Summary'] = summary.apply(
            lambda r: f'Possible PHI/PII finding repeats across {int(r["Affected File Count"])} file(s) with matching Site/Patient/Study and detected value.',
            axis=1,
        )
    summary['Recommended Action'] = 'Site review requested: confirm whether detected value is true PHI/PII and remove or document disposition.'
    summary['Site Finding / Action'] = ''
    summary = summary[
        [
            'Site ID',
            'PatientID',
            'Study Instance UID',
            'Findings',
            'Validation Issue',
            'DICOM Tag / Field',
            'Detected Value',
            'Affected File Count',
            'Example File Name (sent by site)',
            'Example File Path',
            'Details Summary',
            'Recommended Action',
            'Site Finding / Action',
        ]
    ]

    uploaded = (
        all_rows[['Site ID', 'Study Instance UID']]
        .drop_duplicates()
        .groupby('Site ID', dropna=False)['Study Instance UID']
        .nunique()
        .reset_index(name='Total Studies Uploaded')
    )
    if subset.empty:
        counts = pd.DataFrame(columns=['Site ID', 'Total Studies with PHI Findings'])
        header_counts = pd.DataFrame(columns=['Site ID', 'PHI in Header Study Count'])
        pixel_counts = pd.DataFrame(columns=['Site ID', 'Burned-in PHI Pixels Study Count'])
        series_counts = pd.DataFrame(columns=['Site ID', 'Total Series Affected by PHI'])
        file_counts = pd.DataFrame(columns=['Site ID', 'Total Unique Files with PHI'])
    else:
        counts = (
            subset[['Site ID', 'Study Instance UID']]
            .drop_duplicates()
            .groupby('Site ID', dropna=False)['Study Instance UID']
            .nunique()
            .reset_index(name='Total Studies with PHI Findings')
        )
        header_counts = (
            subset[subset['Findings'] == '🙈 Possible PHI/PII in Header'][['Site ID', 'Study Instance UID']]
            .drop_duplicates()
            .groupby('Site ID', dropna=False)['Study Instance UID']
            .nunique()
            .reset_index(name='PHI in Header Study Count')
        )
        pixel_counts = (
            subset[subset['Findings'] == '🖼️ Possible Burned-in PHI/PII (Pixels)'][['Site ID', 'Study Instance UID']]
            .drop_duplicates()
            .groupby('Site ID', dropna=False)['Study Instance UID']
            .nunique()
            .reset_index(name='Burned-in PHI Pixels Study Count')
        )
        series_counts = (
            subset[['Site ID', 'Study Instance UID', 'Series Instance UID']]
            .drop_duplicates()
            .groupby('Site ID', dropna=False)
            .size()
            .reset_index(name='Total Series Affected by PHI')
        )
        file_counts = (
            subset.groupby('Site ID', dropna=False)['File Path']
            .nunique()
            .reset_index(name='Total Unique Files with PHI')
        )

    site_summary = uploaded.merge(counts, on='Site ID', how='left')
    site_summary = site_summary.merge(header_counts, on='Site ID', how='left')
    site_summary = site_summary.merge(pixel_counts, on='Site ID', how='left')
    site_summary = site_summary.merge(series_counts, on='Site ID', how='left')
    site_summary = site_summary.merge(file_counts, on='Site ID', how='left')
    for col in [
        'Total Studies with PHI Findings',
        'PHI in Header Study Count',
        'Burned-in PHI Pixels Study Count',
        'Total Series Affected by PHI',
        'Total Unique Files with PHI',
    ]:
        site_summary[col] = pd.to_numeric(site_summary[col], errors='coerce').fillna(0).astype(int)

    site_summary['Percent Studies with PHI Findings'] = site_summary.apply(
        lambda r: round((float(r['Total Studies with PHI Findings']) / float(r['Total Studies Uploaded']) * 100.0), 2)
        if float(r['Total Studies Uploaded']) > 0
        else pd.NA,
        axis=1,
    )
    site_summary = site_summary.sort_values('Total Studies with PHI Findings', ascending=False)

    grand_total = int(site_summary['Total Studies with PHI Findings'].sum())
    uploaded_total = int(pd.to_numeric(site_summary['Total Studies Uploaded'], errors='coerce').fillna(0).sum())
    grand_row = {
        'Site ID': 'Grand Total',
        'Total Studies Uploaded': uploaded_total,
        'Total Studies with PHI Findings': grand_total,
        'Percent Studies with PHI Findings': round((float(grand_total) / float(uploaded_total)) * 100.0, 2)
        if uploaded_total > 0
        else pd.NA,
        'PHI in Header Study Count': int(site_summary['PHI in Header Study Count'].sum()),
        'Burned-in PHI Pixels Study Count': int(site_summary['Burned-in PHI Pixels Study Count'].sum()),
        'Total Series Affected by PHI': int(site_summary['Total Series Affected by PHI'].sum()),
        'Total Unique Files with PHI': int(site_summary['Total Unique Files with PHI'].sum()),
    }
    site_summary = pd.concat([site_summary, pd.DataFrame([grand_row])], ignore_index=True)

    return detail, summary, site_summary


def build_validation_reports(all_rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    subset = all_rows[all_rows['Findings'].isin(VALIDATION_FINDINGS)].copy()
    subset['File Name (sent by site)'] = subset['File Path'].map(to_site_filename)
    subset['File Name in LabCAS'] = subset['File Name (sent by site)'].map(to_labcas_filename)
    subset['LabCAS URL'] = subset['File Path'].map(build_labcas_url)
    issue_pairs = subset.apply(lambda r: summarize_issue(r['Details'], r['Findings']), axis=1)
    subset['Validation Issue'] = issue_pairs.apply(lambda pair: pair[1])
    subset['Series Instance UID'] = subset.apply(
        lambda r: extract_series_uid(r['Details'], r.get('Series Instance UID', '')),
        axis=1,
    )
    subset['Affected Tag(s)'] = subset.apply(
        lambda r: extract_affected_tags(r['Details'], r['Validation Issue']),
        axis=1,
    )

    detail = subset.copy()
    detail['Recommended Action'] = detail.apply(
        lambda r: recommended_action(r['Validation Issue'], r['Findings']),
        axis=1,
    )
    detail['Site Finding / Action'] = ''
    detail = detail[
        [
            'Site ID',
            'Study Instance UID',
            'Series Instance UID',
            'File Name (sent by site)',
            'File Name in LabCAS',
            'LabCAS URL',
            'File Path',
            'Findings',
            'Validation Issue',
            'Affected Tag(s)',
            'Details',
            'Recommended Action',
            'Site Finding / Action',
        ]
    ].drop_duplicates()
    detail = detail.sort_values(
        by=['Site ID', 'Study Instance UID', 'Series Instance UID', 'Validation Issue', 'File Name (sent by site)'],
        na_position='last',
    )

    group_cols = [
        'Site ID',
        'Study Instance UID',
        'Series Instance UID',
        'Findings',
        'Validation Issue',
        'Affected Tag(s)',
    ]
    summary = subset.groupby(group_cols, dropna=False).agg(
        **{
            'Affected File Count': ('File Name (sent by site)', 'nunique'),
            'File Name (sent by site)': ('File Name (sent by site)', 'first'),
            'File Name in LabCAS': ('File Name in LabCAS', 'first'),
            'LabCAS URL': ('LabCAS URL', 'first'),
            'File Path': ('File Path', 'first'),
        }
    ).reset_index()
    summary['Details Summary'] = summary.apply(
        lambda r: details_summary(r['Findings'], r['Validation Issue'], r['Affected Tag(s)'], int(r['Affected File Count'])),
        axis=1,
    )
    summary['Recommended Action'] = summary.apply(
        lambda r: recommended_action(r['Validation Issue'], r['Findings']),
        axis=1,
    )
    summary['Site Finding / Action'] = ''
    summary = summary[
        [
            'Site ID',
            'Study Instance UID',
            'Series Instance UID',
            'Findings',
            'Validation Issue',
            'Affected Tag(s)',
            'Affected File Count',
            'File Name (sent by site)',
            'File Name in LabCAS',
            'LabCAS URL',
            'File Path',
            'Details Summary',
            'Recommended Action',
            'Site Finding / Action',
        ]
    ]

    uploaded = (
        all_rows[['Site ID', 'Study Instance UID']]
        .drop_duplicates()
        .groupby('Site ID', dropna=False)['Study Instance UID']
        .nunique()
        .reset_index(name='Total Studies Uploaded')
    )
    if subset.empty:
        counts = pd.DataFrame(columns=['Site ID', 'Total Studies with Validation Issues'])
        missing_counts = pd.DataFrame(columns=['Site ID', 'Missing Required Tags Study Count'])
        warning_counts = pd.DataFrame(columns=['Site ID', 'Warnings Study Count'])
        error_counts = pd.DataFrame(columns=['Site ID', 'Critical Errors Study Count'])
        series_counts = pd.DataFrame(columns=['Site ID', 'Total Series Affected'])
        file_counts = pd.DataFrame(columns=['Site ID', 'Total Unique Files Flagged'])
    else:
        counts = (
            subset[['Site ID', 'Study Instance UID']]
            .drop_duplicates()
            .groupby('Site ID', dropna=False)['Study Instance UID']
            .nunique()
            .reset_index(name='Total Studies with Validation Issues')
        )
        missing_counts = (
            subset[subset['Findings'] == '⚠️ Missing Required Tags'][['Site ID', 'Study Instance UID']]
            .drop_duplicates()
            .groupby('Site ID', dropna=False)['Study Instance UID']
            .nunique()
            .reset_index(name='Missing Required Tags Study Count')
        )
        warning_counts = (
            subset[subset['Findings'] == '👮 Warning'][['Site ID', 'Study Instance UID']]
            .drop_duplicates()
            .groupby('Site ID', dropna=False)['Study Instance UID']
            .nunique()
            .reset_index(name='Warnings Study Count')
        )
        error_counts = (
            subset[subset['Findings'] == '❌ Error'][['Site ID', 'Study Instance UID']]
            .drop_duplicates()
            .groupby('Site ID', dropna=False)['Study Instance UID']
            .nunique()
            .reset_index(name='Critical Errors Study Count')
        )
        series_counts = (
            subset[['Site ID', 'Study Instance UID', 'Series Instance UID']]
            .drop_duplicates()
            .groupby('Site ID', dropna=False)
            .size()
            .reset_index(name='Total Series Affected')
        )
        file_counts = (
            subset.groupby('Site ID', dropna=False)['File Path']
            .nunique()
            .reset_index(name='Total Unique Files Flagged')
        )

    site_summary = uploaded.merge(counts, on='Site ID', how='left')
    site_summary = site_summary.merge(missing_counts, on='Site ID', how='left')
    site_summary = site_summary.merge(warning_counts, on='Site ID', how='left')
    site_summary = site_summary.merge(error_counts, on='Site ID', how='left')
    site_summary = site_summary.merge(series_counts, on='Site ID', how='left')
    site_summary = site_summary.merge(file_counts, on='Site ID', how='left')

    for col in [
        'Total Studies with Validation Issues',
        'Missing Required Tags Study Count',
        'Warnings Study Count',
        'Critical Errors Study Count',
        'Total Series Affected',
        'Total Unique Files Flagged',
    ]:
        site_summary[col] = pd.to_numeric(site_summary[col], errors='coerce').fillna(0).astype(int)

    site_summary['Percent Studies with Validation Issues'] = site_summary.apply(
        lambda r: round((float(r['Total Studies with Validation Issues']) / float(r['Total Studies Uploaded']) * 100.0), 2)
        if float(r['Total Studies Uploaded']) > 0
        else pd.NA,
        axis=1,
    )
    site_summary = site_summary.sort_values('Total Studies with Validation Issues', ascending=False)

    grand_total = int(site_summary['Total Studies with Validation Issues'].sum())
    uploaded_total = int(pd.to_numeric(site_summary['Total Studies Uploaded'], errors='coerce').fillna(0).sum())
    grand_row = {
        'Site ID': 'Grand Total',
        'Total Studies Uploaded': uploaded_total,
        'Total Studies with Validation Issues': grand_total,
        'Percent Studies with Validation Issues': round((float(grand_total) / float(uploaded_total)) * 100.0, 2)
        if uploaded_total > 0
        else pd.NA,
        'Missing Required Tags Study Count': int(site_summary['Missing Required Tags Study Count'].sum()),
        'Warnings Study Count': int(site_summary['Warnings Study Count'].sum()),
        'Critical Errors Study Count': int(site_summary['Critical Errors Study Count'].sum()),
        'Total Series Affected': int(site_summary['Total Series Affected'].sum()),
        'Total Unique Files Flagged': int(site_summary['Total Unique Files Flagged'].sum()),
    }
    site_summary = pd.concat([site_summary, pd.DataFrame([grand_row])], ignore_index=True)

    return detail, summary, site_summary


def load_pdac_sources(input_files: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in input_files:
        if not path.exists():
            raise SystemExit(f'Input file does not exist: {path}')

        header_cols = list(pd.read_csv(path, dtype=str, nrows=0).columns)
        missing = [c for c in REQUIRED_COLUMNS if c not in header_cols]
        if missing:
            raise SystemExit(f'Missing required columns in {path.name}: {missing}')

        source_columns = REQUIRED_COLUMNS + [column for column in ['PatientID'] if column in header_cols]
        frames.append(pd.read_csv(path, dtype=str, usecols=source_columns))

    all_rows = pd.concat(frames, ignore_index=True)
    for col in REQUIRED_COLUMNS:
        all_rows[col] = all_rows[col].fillna('')
    if 'PatientID' not in all_rows.columns:
        all_rows['PatientID'] = ''
    else:
        all_rows['PatientID'] = all_rows['PatientID'].fillna('')
    return all_rows


def build_pivot(df: pd.DataFrame, out_path: Path) -> None:
    subset = df[df['Findings'].isin([
        '🖼️ Possible Burned-in PHI/PII (Pixels)',
        '🙈 Possible PHI/PII in Header',
        '⚠️ Missing Required Tags',
        '👮 Warning',
        '❌ Error',
    ])].copy()
    if subset.empty:
        pd.DataFrame(columns=['Findings', 'Validation Issue']).to_csv(out_path, index=False)
        return

    issue_pairs = subset.apply(lambda r: summarize_issue(r['Details'], r['Findings']), axis=1)
    subset['Validation Issue'] = issue_pairs.apply(lambda pair: pair[1])
    grouped = subset.groupby(['Findings', 'Validation Issue', 'Profile'], dropna=False)['File Path'].nunique().reset_index(name='Count')
    pivot = grouped.pivot_table(index=['Findings', 'Validation Issue'], columns='Profile', values='Count', fill_value=0)
    pivot['Grand Total'] = pivot.sum(axis=1)
    pivot = pivot.reset_index()

    profile_cols = [c for c in pivot.columns if c not in {'Findings', 'Validation Issue', 'Grand Total'}]
    col_totals = {'Findings': 'Grand Total', 'Validation Issue': ''}
    for c in profile_cols:
        col_totals[c] = int(pivot[c].sum())
    col_totals['Grand Total'] = int(pivot['Grand Total'].sum())
    pivot = pd.concat([pivot, pd.DataFrame([col_totals])], ignore_index=True, sort=False)
    pivot.to_csv(out_path, index=False)


def build_investigator_summary(all_rows: pd.DataFrame) -> pd.DataFrame:
    df = all_rows.copy()
    df['Findings Category'] = df['Findings'].map(categorize_finding)
    df['Tag Name'] = df['Details'].map(extract_tag_name)

    df = df.drop_duplicates(
        subset=[
            'Site ID',
            'Study Instance UID',
            'Series Instance UID',
            'File Path',
            'Findings Category',
            'Tag Name',
            'Details',
        ]
    )

    site_uploaded = (
        all_rows[['Site ID', 'Study Instance UID']]
        .drop_duplicates()
        .groupby('Site ID', dropna=False)['Study Instance UID']
        .nunique()
        .reset_index(name='Total Studies Uploaded')
    )

    base = (
        df.groupby('Site ID', dropna=False)
        .agg(
            **{
                'Total Studies with Validation Issues': ('Study Instance UID', 'nunique'),
                'Total Unique Files Flagged': ('File Path', 'nunique'),
            }
        )
        .reset_index()
    )

    series_counts = (
        df[['Site ID', 'Study Instance UID', 'Series Instance UID']]
        .drop_duplicates()
        .groupby('Site ID', dropna=False)
        .size()
        .reset_index(name='Total Series Affected')
    )
    base = base.merge(series_counts, on='Site ID', how='left')

    out = site_uploaded.merge(base, on='Site ID', how='left')
    out['Total Studies with Validation Issues'] = pd.to_numeric(
        out['Total Studies with Validation Issues'], errors='coerce'
    ).fillna(0).astype(int)
    out['Total Series Affected'] = pd.to_numeric(out['Total Series Affected'], errors='coerce').fillna(0).astype(int)
    out['Total Unique Files Flagged'] = pd.to_numeric(
        out['Total Unique Files Flagged'], errors='coerce'
    ).fillna(0).astype(int)

    out['Percent Studies with Validation Issues'] = out.apply(
        lambda r: round((float(r['Total Studies with Validation Issues']) / float(r['Total Studies Uploaded']) * 100.0), 2)
        if float(r['Total Studies Uploaded']) > 0
        else pd.NA,
        axis=1,
    )

    cat_counts = (
        df.groupby(['Site ID', 'Findings Category'], dropna=False)['Study Instance UID']
        .nunique()
        .unstack(fill_value=0)
        .reset_index()
    )
    out = out.merge(cat_counts, on='Site ID', how='left')

    for col in [
        'Missing Required Tags',
        'Critical Errors',
        'Warnings',
        'PHI in Header',
        'Burned-in PHI (Pixels)',
    ]:
        if col not in out.columns:
            out[col] = 0

    out = out.rename(
        columns={
            'Missing Required Tags': 'Missing Required Tags Study Count',
            'Critical Errors': 'Critical Errors Study Count',
            'Warnings': 'Warnings Study Count',
            'PHI in Header': 'PHI in Header Study Count',
            'Burned-in PHI (Pixels)': 'Burned-in PHI Pixels Study Count',
        }
    )

    category_count_cols = [
        'Missing Required Tags Study Count',
        'Critical Errors Study Count',
        'Warnings Study Count',
        'PHI in Header Study Count',
        'Burned-in PHI Pixels Study Count',
    ]

    for count_col in category_count_cols:
        pct_col = count_col.replace(' Study Count', ' % Studies with Issues')
        out[pct_col] = out.apply(
            lambda r: round((float(r[count_col]) / float(r['Total Studies Uploaded']) * 100.0), 2)
            if float(r['Total Studies Uploaded']) > 0
            else pd.NA,
            axis=1,
        )

    ordered_cols = [
        'Site ID',
        'Total Studies Uploaded',
        'Total Studies with Validation Issues',
        'Percent Studies with Validation Issues',
        'Total Series Affected',
        'Total Unique Files Flagged',
        'Missing Required Tags Study Count',
        'Missing Required Tags % Studies with Issues',
        'Critical Errors Study Count',
        'Critical Errors % Studies with Issues',
        'Warnings Study Count',
        'Warnings % Studies with Issues',
        'PHI in Header Study Count',
        'PHI in Header % Studies with Issues',
        'Burned-in PHI Pixels Study Count',
        'Burned-in PHI Pixels % Studies with Issues',
    ]
    out = out[ordered_cols].sort_values(by='Total Studies with Validation Issues', ascending=False)

    total_row = {'Site ID': 'Grand Total'}
    for col in ordered_cols[1:]:
        if col.endswith('% Studies with Issues') or col == 'Percent Studies with Validation Issues':
            continue
        total_row[col] = int(pd.to_numeric(out[col], errors='coerce').fillna(0).sum())

    uploaded = float(total_row.get('Total Studies Uploaded', 0))
    affected = float(total_row.get('Total Studies with Validation Issues', 0))
    total_row['Percent Studies with Validation Issues'] = round((affected / uploaded) * 100.0, 2) if uploaded > 0 else pd.NA

    for count_col in category_count_cols:
        pct_col = count_col.replace(' Study Count', ' % Studies with Issues')
        count_val = float(total_row.get(count_col, 0))
        total_row[pct_col] = round((count_val / uploaded) * 100.0, 2) if uploaded > 0 else pd.NA

    return pd.concat([out, pd.DataFrame([total_row])], ignore_index=True)


def has_ctdivol(findings: str, details: str) -> bool:
    blob = f'{(findings or "")} {(details or "")}'.lower()
    return bool(re.search(r'\bctdivol\b|\(0018,\s*9345\)', blob, flags=re.IGNORECASE))


def is_missing_required_finding(findings: str) -> bool:
    return bool(re.search(r'missing\s+required|missing\s+required\s+tags', findings or '', flags=re.IGNORECASE))


def is_warning_finding(findings: str) -> bool:
    return bool(re.search(r'warning', findings or '', flags=re.IGNORECASE))


def build_ctdivol_summary(
    all_rows: pd.DataFrame,
    mode: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = all_rows.copy()

    if mode == 'missing-required':
        flagged = df[
            df.apply(lambda r: has_ctdivol(r['Findings'], r['Details']), axis=1)
            & df['Findings'].map(is_missing_required_finding)
        ].copy()
        count_col = 'Total Studies with Missing CTDIvol (Missing Required)'
        pct_col = 'Percent Studies with Missing CTDIvol (Missing Required)'
    else:
        flagged = df[
            df.apply(lambda r: has_ctdivol(r['Findings'], r['Details']), axis=1)
            & df['Findings'].map(is_warning_finding)
        ].copy()
        count_col = 'Total Studies with Missing CTDIvol (Optional Warning)'
        pct_col = 'Percent Studies with Missing CTDIvol (Optional Warning)'

    uploaded = (
        all_rows[['Site ID', 'Study Instance UID']]
        .drop_duplicates()
        .groupby('Site ID', dropna=False)['Study Instance UID']
        .nunique()
        .reset_index(name='Total Studies Uploaded')
    )

    if flagged.empty:
        counts = pd.DataFrame(columns=['Site ID', count_col])
    else:
        counts = (
            flagged[['Site ID', 'Study Instance UID']]
            .drop_duplicates()
            .groupby('Site ID', dropna=False)['Study Instance UID']
            .nunique()
            .reset_index(name=count_col)
        )

    summary = uploaded.merge(counts, on='Site ID', how='left')
    summary[count_col] = pd.to_numeric(summary[count_col], errors='coerce').fillna(0).astype(int)
    summary[pct_col] = summary.apply(
        lambda r: round((float(r[count_col]) / float(r['Total Studies Uploaded']) * 100.0), 2)
        if float(r['Total Studies Uploaded']) > 0
        else pd.NA,
        axis=1,
    )
    summary = summary.sort_values(count_col, ascending=False)

    grand_total = int(summary[count_col].sum())
    uploaded_total = int(pd.to_numeric(summary['Total Studies Uploaded'], errors='coerce').fillna(0).sum())
    grand_pct = round((float(grand_total) / float(uploaded_total)) * 100.0, 2) if uploaded_total > 0 else pd.NA
    summary = pd.concat(
        [
            summary,
            pd.DataFrame(
                [
                    {
                        'Site ID': 'Grand Total',
                        'Total Studies Uploaded': uploaded_total,
                        count_col: grand_total,
                        pct_col: grand_pct,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    detail = flagged[
        [
            'Site ID',
            'Study Instance UID',
            'Series Instance UID',
            'File Path',
            'Findings',
            'Details',
        ]
    ].drop_duplicates()

    return summary, detail


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Build PDAC validation CSV reports per-site (never combined across sites).'
    )
    parser.add_argument(
        '--input-files',
        nargs='+',
        default=[
            '/Users/hkincaid/Documents/JPL/LabCAS/DICOM/ValidationReports/PDAC/BCM.csv',
            '/Users/hkincaid/Documents/JPL/LabCAS/DICOM/ValidationReports/PDAC/UPMC.csv',
        ],
        help='Raw PDAC validation CSV files to process.',
    )
    parser.add_argument(
        '--output-dir',
        default='/Users/hkincaid/Documents/JPL/LabCAS/DICOM/ValidationReports/PDAC',
        help='Output directory for generated PDAC report CSVs.',
    )
    parser.add_argument(
        '--report-date',
        default=date.today().strftime('%Y%m%d'),
        help='Date stamp for output filenames in YYYYMMDD format.',
    )
    args = parser.parse_args()

    input_files = [Path(p) for p in args.input_files]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f'Processing {len(input_files)} PDAC site source file(s) with date {args.report_date}')

    for input_file in input_files:
        site_rows = load_pdac_sources([input_file])
        site_label = input_file.stem.upper()

        validation_detail, validation_summary, _ = build_validation_reports(site_rows)
        _, phi_summary, _ = build_phi_reports(site_rows)
        validation_detail_path = output_dir / f'PDAC_{site_label}_ValidationDetail_{args.report_date}.csv'
        validation_summary_path = output_dir / f'PDAC_{site_label}_PossibleValidationIssues_report_{args.report_date}.csv'
        pivot_path = output_dir / f'PDAC_{site_label}_Summary_Pivot_DetectedValues_{args.report_date}.csv'
        phi_summary_path = output_dir / f'PDAC_{site_label}_PHI_Summary_for_Site_Review_Rolled_Up_{args.report_date}.csv'
        validation_detail.to_csv(validation_detail_path, index=False)
        validation_summary.to_csv(validation_summary_path, index=False)
        phi_summary.to_csv(phi_summary_path, index=False)
        build_pivot(site_rows, pivot_path)

        print(f'Wrote validation detail: {validation_detail_path}')
        print(f'Wrote possible validation issues report: {validation_summary_path}')
        print(f'Wrote rolled-up PHI summary: {phi_summary_path}')
        print(f'Wrote pivot summary: {pivot_path}')


if __name__ == '__main__':
    main()
