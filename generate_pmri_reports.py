#!/usr/bin/env python3
from pathlib import Path
import argparse
import pandas as pd
import re

base_dir = Path('/Users/hkincaid/Documents/JPL/LabCAS/DICOM/ValidationReports/Prostate_MRI')


def output_paths(raw_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    source_stem = raw_path.stem
    out_dir = raw_path.parent
    phi_summary_out = out_dir / f'{source_stem}_PHI_Summary_for_Site_Review.csv'
    phi_detail_out = out_dir / f'{source_stem}_PHI_Detail.csv'
    validation_summary_out = out_dir / f'{source_stem}_PMRI_PossibleValidationIssues_report.csv'
    validation_detail_out = out_dir / f'{source_stem}_PMRI_ValidationDetail.csv'
    pivot_out = out_dir / f'{source_stem}_Summary_Pivot_DetectedValues.csv'
    return phi_summary_out, phi_detail_out, validation_summary_out, validation_detail_out, pivot_out


def _clean(text: str) -> str:
    if not isinstance(text, str):
        return ''
    text = text.strip()
    return text


def to_labcas_filename(site_filename: str, event_id: str) -> str:
    name = _clean(site_filename)
    eid = _clean(event_id)
    if not name:
        return ''
    if not eid:
        eid = 'UNKNOWN'
    if name.lower().endswith('.dcm'):
        return f'{name[:-4]}_{eid}.dcm'
    return f'{name}_{eid}.dcm'


def to_site_upload_path(value: str) -> str:
    return _clean(value)


def to_site_basename(site_upload_path: str) -> str:
    path_value = _clean(site_upload_path)
    if not path_value:
        return ''
    return Path(path_value).name


def normalize_input_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Accept either File Path or File Name input and standardize on File Path.
    if 'File Path' not in df.columns and 'File Name' in df.columns:
        df['File Path'] = df['File Name']
    return df


def extract_series_uid(details: str, fallback_series_uid: str) -> str:
    text = _clean(details)
    match = re.search(r'(?:Series\s*Instance\s*UID|SeriesInstanceUID)\s*[:=]\s*([0-9]+(?:\.[0-9]+)+)', text, flags=re.IGNORECASE)
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
        return f'{issue} appears across {count} file(s) in this event/series. Affected tag(s): {affected_tags}.'
    if issue.startswith('Invalid format:'):
        return f'{issue} appears across {count} file(s) in this event/series.'
    if _clean(findings) == '❌ Error':
        return f'{issue} appears across {count} file(s) in this event/series.'
    return f'{issue} appears across {count} file(s) in this event/series.'


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


def summarize_issue(details: str, finding: str) -> tuple[str, str]:
    text = _clean(details)
    if not text:
        return '', ''

    def extract_tag_name(source: str) -> str:
        match = re.search(r'Required tag not found in DICOM dataset:\s*\((?:[0-9A-Fa-f]{4},[0-9A-Fa-f]{4})\)\s*\(?([A-Za-z0-9_]+)\)?', source)
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
        path_match = re.search(r'path "([^"]+)"', text)
        path_tag = ''
        if path_match:
            path_tag = path_match.group(1).split('.')[-1]

        tag_matches = re.findall(r'\((?:[0-9A-Fa-f]{4},[0-9A-Fa-f]{4})\) \(([A-Za-z0-9_]+)\)', text)
        tag = path_tag or (tag_matches[-1] if tag_matches else '')
        if not tag:
            tag_match = re.search(r'Strict high-risk tag "([^"]+)"', text)
            if not tag_match:
                tag_match = re.search(r'High-risk tag: ([A-Za-z0-9_]+)', text)
            tag = tag_match.group(1) if tag_match else text

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
            tag = extract_tag_name(text)
            return tag, f'Missing tag: {tag}'

        if 'does not match expected pattern' in lowered or 'must not be numeric-only' in lowered or 'cannot have leading or trailing spaces' in lowered:
            match = re.search(r'Value for tag does not match expected pattern:\s*([A-Za-z0-9_]+)\s*(.*)$', text)
            if match:
                tag = match.group(1)
                reason = trim_boilerplate(match.group(2))
                value = f'{tag} {reason}'.strip()
                return tag, f'Invalid format: {value}'
            tag = extract_tag_name(text)
            return tag, f'Invalid format: {tag}'

        if 'windowcenter' in lowered or 'windowwidth' in lowered:
            tag = 'WindowCenter' if 'windowcenter' in lowered else 'WindowWidth'
            return tag, f'Missing tag: {tag}'

        return text, text

    if finding == '❌ Error':
        return text, f'Error: {text}'

    return text, text


def build_phi_reports(df: pd.DataFrame, findings: list[str], summary_out_path: Path, detail_out_path: Path) -> None:
    subset = df[df['Findings'].isin(findings)].copy()
    subset = subset[['Event ID', 'File Path', 'Study Instance UID', 'Series Instance UID', 'Profile', 'Findings', 'Details']].copy()
    subset.rename(columns={'File Path': 'Site Upload Path'}, inplace=True)
    subset['LabCAS Filename'] = subset.apply(lambda r: to_labcas_filename(to_site_basename(r['Site Upload Path']), r['Event ID']), axis=1)
    issue_pairs = subset.apply(lambda r: summarize_issue(r['Details'], r['Findings']), axis=1)
    subset['Validation Issue'] = issue_pairs.apply(lambda pair: pair[1])
    subset['Series Instance UID'] = subset.apply(lambda r: extract_series_uid(r['Details'], r.get('Series Instance UID', '')), axis=1)
    phi_parsed = subset.apply(lambda r: parse_phi_field_and_value(r['Validation Issue'], r['Details'], r['Findings']), axis=1)
    subset['DICOM Tag / Field'] = phi_parsed.apply(lambda pair: pair[0])
    subset['Detected Value'] = phi_parsed.apply(lambda pair: pair[1])

    detail = subset.copy()
    detail['Reconciliation Status'] = 'Needs PHI reconciliation'
    detail['Action'] = 'Review each affected file and reconcile exact detected value.'
    detail = detail[['Event ID', 'Study Instance UID', 'Series Instance UID', 'Site Upload Path', 'LabCAS Filename', 'Findings', 'Validation Issue', 'DICOM Tag / Field', 'Detected Value', 'Details', 'Reconciliation Status', 'Action']]
    detail = detail.sort_values(by=['Event ID', 'Study Instance UID', 'Series Instance UID', 'Validation Issue', 'Site Upload Path'], na_position='last')
    detail.to_csv(detail_out_path, index=False)

    group_cols = ['Event ID', 'Study Instance UID', 'Findings', 'DICOM Tag / Field', 'Detected Value', 'Validation Issue']
    summary = subset.groupby(group_cols, dropna=False).agg(
        **{
            'Affected File Count': ('Site Upload Path', 'nunique'),
            'Example Site Upload Path': ('Site Upload Path', 'first'),
            'Example LabCAS Filename': ('LabCAS Filename', 'first'),
            'Details': ('Details', 'first'),
        }
    ).reset_index()
    if summary.empty:
        summary['Details Summary'] = ''
    else:
        summary['Details Summary'] = summary.apply(
            lambda r: f"Possible PHI/PII finding repeats across {int(r['Affected File Count'])} file(s) with matching Event/Study and detected value.",
            axis=1,
        )
    summary['Recommended Action'] = 'Site review requested: confirm whether detected value is true PHI/PII and remove or document disposition.'
    summary['Site Finding / Action'] = ''
    summary = summary[['Event ID', 'Study Instance UID', 'Findings', 'Validation Issue', 'DICOM Tag / Field', 'Detected Value', 'Affected File Count', 'Example Site Upload Path', 'Example LabCAS Filename', 'Details Summary', 'Recommended Action', 'Site Finding / Action']]
    summary = summary.sort_values(by=['Event ID', 'Study Instance UID', 'Validation Issue', 'DICOM Tag / Field', 'Detected Value'], na_position='last')
    summary.to_csv(summary_out_path, index=False)


def build_validation_reports(df: pd.DataFrame, summary_out_path: Path, detail_out_path: Path) -> None:
    subset = df[df['Findings'].isin(['⚠️ Missing Required Tags', '❌ Error'])].copy()
    subset = subset[['Event ID', 'File Path', 'Series Instance UID', 'Profile', 'Findings', 'Details']].copy()
    subset.rename(columns={'File Path': 'Site Upload Path'}, inplace=True)
    subset['LabCAS Filename'] = subset.apply(lambda r: to_labcas_filename(to_site_basename(r['Site Upload Path']), r['Event ID']), axis=1)
    issue_pairs = subset.apply(lambda r: summarize_issue(r['Details'], r['Findings']), axis=1)
    subset['Validation Issue'] = issue_pairs.apply(lambda pair: pair[1])
    subset['Series Instance UID'] = subset.apply(lambda r: extract_series_uid(r['Details'], r.get('Series Instance UID', '')), axis=1)
    subset['Affected Tag(s)'] = subset.apply(lambda r: extract_affected_tags(r['Details'], r['Validation Issue']), axis=1)

    detail = subset.copy()
    detail['Recommended Action'] = detail.apply(lambda r: recommended_action(r['Validation Issue'], r['Findings']), axis=1)
    detail['Site Finding / Action'] = ''
    detail = detail[['Event ID', 'Series Instance UID', 'Site Upload Path', 'LabCAS Filename', 'Findings', 'Validation Issue', 'Affected Tag(s)', 'Details', 'Recommended Action', 'Site Finding / Action']]
    detail = detail.sort_values(by=['Event ID', 'Series Instance UID', 'Validation Issue', 'Site Upload Path'], na_position='last')
    detail.to_csv(detail_out_path, index=False)

    group_cols = ['Event ID', 'Series Instance UID', 'Findings', 'Validation Issue', 'Affected Tag(s)']
    summary = subset.groupby(group_cols, dropna=False).agg(
        **{
            'Affected File Count': ('Site Upload Path', 'nunique'),
            'Site Upload Path': ('Site Upload Path', 'first'),
            'LabCAS Filename': ('LabCAS Filename', 'first'),
            'Details': ('Details', 'first'),
        }
    ).reset_index()
    if summary.empty:
        summary['Details Summary'] = ''
    else:
        summary['Details Summary'] = summary.apply(
            lambda r: details_summary(r['Findings'], r['Validation Issue'], r['Affected Tag(s)'], int(r['Affected File Count'])),
            axis=1,
        )
    summary['Recommended Action'] = summary.apply(lambda r: recommended_action(r['Validation Issue'], r['Findings']), axis=1)
    summary['Site Finding / Action'] = ''
    summary = summary[['Event ID', 'Series Instance UID', 'Findings', 'Validation Issue', 'Affected Tag(s)', 'Affected File Count', 'Site Upload Path', 'LabCAS Filename', 'Details Summary', 'Recommended Action', 'Site Finding / Action']]
    summary = summary.sort_values(by=['Event ID', 'Series Instance UID', 'Validation Issue', 'Affected Tag(s)'], na_position='last')
    summary.to_csv(summary_out_path, index=False)


def build_pivot(df: pd.DataFrame, out_path: Path) -> None:
    subset = df[df['Findings'].isin([
        '🖼️ Possible Burned-in PHI/PII (Pixels)',
        '🙈 Possible PHI/PII in Header',
        '⚠️ Missing Required Tags',
        '👮 Warning',
        '❌ Error',
    ])].copy()
    issue_pairs = subset.apply(lambda r: summarize_issue(r['Details'], r['Findings']), axis=1)
    subset['Validation Issue'] = issue_pairs.apply(lambda pair: pair[1])
    grouped = subset.groupby(['Findings', 'Validation Issue', 'Profile'])['File Path'].nunique().reset_index(name='Count')
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate PMRI report CSVs from a source validation CSV.')
    parser.add_argument(
        'source_csv',
        nargs='?',
        default=str(base_dir / 'PMRI-Site10.csv'),
        help='Path to source CSV (default: PMRI-Site10.csv in Prostate_MRI).',
    )
    args = parser.parse_args()

    raw_path = Path(args.source_csv)
    phi_summary_out, phi_detail_out, validation_summary_out, validation_detail_out, pivot_out = output_paths(raw_path)

    df = pd.read_csv(raw_path, dtype=str)
    df = normalize_input_columns(df)
    df['Details'] = df['Details'].fillna('')
    build_phi_reports(df, ['🖼️ Possible Burned-in PHI/PII (Pixels)', '🙈 Possible PHI/PII in Header'], phi_summary_out, phi_detail_out)
    build_validation_reports(df, validation_summary_out, validation_detail_out)
    build_pivot(df, pivot_out)
    print('Wrote', phi_summary_out)
    print('Wrote', phi_detail_out)
    print('Wrote', validation_summary_out)
    print('Wrote', validation_detail_out)
    print('Wrote', pivot_out)