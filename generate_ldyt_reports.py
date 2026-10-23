#!/usr/bin/env python3
import argparse
from pathlib import Path
import pandas as pd
import re
from typing import Optional

DEFAULT_OUTPUT_DIR = Path('/Users/hkincaid/Documents/JPL/LTP2/ValidationReports/Lung_Team_Project_2')
REPORT_CHOICES = ['phi-summary', 'phi-detail', 'validation-summary', 'validation-detail', 'pivot', 'all']


def infer_project_prefix(raw_path: Path, explicit_prefix: Optional[str]) -> str:
    if explicit_prefix:
        return explicit_prefix.upper()

    lowered = str(raw_path).lower()
    if 'pmri' in lowered or 'prostate_mri' in lowered:
        return 'PMRI'
    return 'LTP2'


def output_paths(raw_path: Path, output_dir: Path, project_prefix: str) -> tuple[Path, Path, Path, Path, Path]:
    source_stem = raw_path.stem
    phi_summary_out = output_dir / f'{source_stem}_{project_prefix}_PHI_Summary_for_Site_Review.csv'
    phi_detail_out = output_dir / f'{source_stem}_{project_prefix}_PHI_Detail.csv'
    validation_summary_out = output_dir / f'{source_stem}_{project_prefix}_PossibleValidationIssues_report.csv'
    validation_detail_out = output_dir / f'{source_stem}_{project_prefix}_ValidationDetail.csv'
    pivot_out = output_dir / f'{source_stem}_{project_prefix}_Summary_Pivot_DetectedValues.csv'
    return phi_summary_out, phi_detail_out, validation_summary_out, validation_detail_out, pivot_out


def normalize_report_selection(selected_reports: list[str]) -> set[str]:
    if 'all' in selected_reports:
        return {'phi-summary', 'phi-detail', 'validation-summary', 'validation-detail', 'pivot'}
    return set(selected_reports)


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


def extract_series_uid(details: str, fallback_series_uid: str) -> str:
    text = _clean(details)
    match = re.search(r'(?:Series\s*Instance\s*UID|SeriesInstanceUID)\s*[:=]\s*([0-9]+(?:\.[0-9]+)+)', text, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return _clean(fallback_series_uid)


def site_file_name(file_path: str) -> str:
    text = _clean(file_path)
    if not text:
        return ''
    return Path(text).name


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
    subset = subset[['Event ID', 'File Name', 'Study Instance UID', 'Series Instance UID', 'Profile', 'Findings', 'Details']].copy()
    subset.rename(columns={'File Name': 'File Name (sent by site)'}, inplace=True)
    subset['File Name in LabCAS'] = subset.apply(lambda r: to_labcas_filename(r['File Name (sent by site)'], r['Event ID']), axis=1)
    issue_pairs = subset.apply(lambda r: summarize_issue(r['Details'], r['Findings']), axis=1)
    subset['Validation Issue'] = issue_pairs.apply(lambda pair: pair[1])
    subset['Series Instance UID'] = subset.apply(lambda r: extract_series_uid(r['Details'], r.get('Series Instance UID', '')), axis=1)
    phi_parsed = subset.apply(lambda r: parse_phi_field_and_value(r['Validation Issue'], r['Details'], r['Findings']), axis=1)
    subset['DICOM Tag / Field'] = phi_parsed.apply(lambda pair: pair[0])
    subset['Detected Value'] = phi_parsed.apply(lambda pair: pair[1])

    # PHI detail (file-level traceability)
    detail = subset.copy()
    detail['Reconciliation Status'] = 'Needs PHI reconciliation'
    detail['Action'] = 'Review each affected file and reconcile exact detected value.'
    detail = detail[['Event ID', 'Study Instance UID', 'Series Instance UID', 'File Name (sent by site)', 'File Name in LabCAS', 'Findings', 'Validation Issue', 'DICOM Tag / Field', 'Detected Value', 'Details', 'Reconciliation Status', 'Action']]
    detail = detail.sort_values(by=['Event ID', 'Study Instance UID', 'Series Instance UID', 'Validation Issue', 'File Name (sent by site)'], na_position='last')
    detail.to_csv(detail_out_path, index=False)

    # PHI summary for site review
    group_cols = ['Event ID', 'Study Instance UID', 'Findings', 'DICOM Tag / Field', 'Detected Value', 'Validation Issue']
    summary = subset.groupby(group_cols, dropna=False).agg(
        **{
            'Affected File Count': ('File Name (sent by site)', 'nunique'),
            'Example File Name (sent by site)': ('File Name (sent by site)', 'first'),
            'Example File Name in LabCAS': ('File Name in LabCAS', 'first'),
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
    summary = summary[['Event ID', 'Study Instance UID', 'Findings', 'Validation Issue', 'DICOM Tag / Field', 'Detected Value', 'Affected File Count', 'Example File Name (sent by site)', 'Example File Name in LabCAS', 'Details Summary', 'Recommended Action', 'Site Finding / Action']]
    summary = summary.sort_values(by=['Event ID', 'Study Instance UID', 'Validation Issue', 'DICOM Tag / Field', 'Detected Value'], na_position='last')
    summary.to_csv(summary_out_path, index=False)


def build_validation_reports(df: pd.DataFrame, summary_out_path: Path, detail_out_path: Path) -> None:
    subset = df[df['Findings'].isin(['⚠️ Missing Required Tags', '❌ Error'])].copy()
    subset = subset[['Event ID', 'File Name', 'Series Instance UID', 'Profile', 'Findings', 'Details']].copy()
    subset.rename(columns={'File Name': 'File Name (sent by site)'}, inplace=True)
    subset['File Name in LabCAS'] = subset.apply(lambda r: to_labcas_filename(r['File Name (sent by site)'], r['Event ID']), axis=1)
    issue_pairs = subset.apply(lambda r: summarize_issue(r['Details'], r['Findings']), axis=1)
    subset['Validation Issue'] = issue_pairs.apply(lambda pair: pair[1])
    subset['Series Instance UID'] = subset.apply(lambda r: extract_series_uid(r['Details'], r.get('Series Instance UID', '')), axis=1)
    subset['Affected Tag(s)'] = subset.apply(lambda r: extract_affected_tags(r['Details'], r['Validation Issue']), axis=1)

    # Validation Detail (file-level rows retained for traceability)
    detail = subset.copy()
    detail['Recommended Action'] = detail.apply(lambda r: recommended_action(r['Validation Issue'], r['Findings']), axis=1)
    detail['Site Finding / Action'] = ''
    detail = detail[['Event ID', 'Series Instance UID', 'File Name (sent by site)', 'File Name in LabCAS', 'Findings', 'Validation Issue', 'Affected Tag(s)', 'Details', 'Recommended Action', 'Site Finding / Action']]
    detail = detail.sort_values(by=['Event ID', 'Series Instance UID', 'Validation Issue', 'File Name (sent by site)'], na_position='last')
    detail.to_csv(detail_out_path, index=False)

    # Validation Summary for Site Review (grouped rows)
    group_cols = ['Event ID', 'Series Instance UID', 'Findings', 'Validation Issue', 'Affected Tag(s)']
    summary = subset.groupby(group_cols, dropna=False).agg(
        **{
            'Affected File Count': ('File Name (sent by site)', 'nunique'),
            'File Name (sent by site)': ('File Name (sent by site)', 'first'),
            'File Name in LabCAS': ('File Name in LabCAS', 'first'),
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
    summary = summary[['Event ID', 'Series Instance UID', 'Findings', 'Validation Issue', 'Affected Tag(s)', 'Affected File Count', 'File Name (sent by site)', 'File Name in LabCAS', 'Details Summary', 'Recommended Action', 'Site Finding / Action']]
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
    grouped = subset.groupby(['Findings', 'Validation Issue', 'Profile'])['File Name'].nunique().reset_index(name='Count')
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
    parser = argparse.ArgumentParser(description='Generate LTP2/PMRI report CSVs from a source validation CSV.')
    parser.add_argument(
        'source_csv',
        nargs='?',
        default=str(DEFAULT_OUTPUT_DIR / 'ldytNSGnHnrBQ.csv'),
        help='Path to source CSV (default: ldytNSGnHnrBQ.csv in Lung_Team_Project_2).',
    )
    parser.add_argument(
        '--output-dir',
        default=None,
        help='Directory for generated reports (default: source CSV parent directory).',
    )
    parser.add_argument(
        '--project-prefix',
        choices=['LTP2', 'PMRI'],
        default=None,
        help='Project prefix for output report names. If omitted, inferred from the source path.',
    )
    parser.add_argument(
        '--reports',
        nargs='+',
        choices=REPORT_CHOICES,
        default=['all'],
        help='Reports to generate. Use one or more of: phi-summary, phi-detail, validation-summary, validation-detail, pivot, all.',
    )
    args = parser.parse_args()

    raw_path = Path(args.source_csv)
    output_dir = Path(args.output_dir) if args.output_dir else raw_path.parent
    project_prefix = infer_project_prefix(raw_path, args.project_prefix)
    selected_reports = normalize_report_selection(args.reports)
    phi_summary_out, phi_detail_out, validation_summary_out, validation_detail_out, pivot_out = output_paths(raw_path, output_dir, project_prefix)

    df = pd.read_csv(raw_path, dtype=str)
    df['Details'] = df['Details'].fillna('')
    if 'File Name' not in df.columns and 'File Path' in df.columns:
        df['File Name'] = df['File Path'].map(site_file_name)

    needs_phi = bool({'phi-summary', 'phi-detail'} & selected_reports)
    needs_validation = bool({'validation-summary', 'validation-detail'} & selected_reports)

    if needs_phi:
        build_phi_reports(df, ['🖼️ Possible Burned-in PHI/PII (Pixels)', '🙈 Possible PHI/PII in Header'], phi_summary_out, phi_detail_out)
    if needs_validation:
        build_validation_reports(df, validation_summary_out, validation_detail_out)
    if 'pivot' in selected_reports:
        build_pivot(df, pivot_out)

    if 'phi-summary' in selected_reports:
        print('Wrote', phi_summary_out)
    if 'phi-detail' in selected_reports:
        print('Wrote', phi_detail_out)
    if 'validation-summary' in selected_reports:
        print('Wrote', validation_summary_out)
    if 'validation-detail' in selected_reports:
        print('Wrote', validation_detail_out)
    if 'pivot' in selected_reports:
        print('Wrote', pivot_out)
