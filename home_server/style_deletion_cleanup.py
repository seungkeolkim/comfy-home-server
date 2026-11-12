"""폐기한 조합의 Render·출력·CHS 요청을 제거하고 공유 작업의 남은 요청을 보존합니다."""


def remove_deleted_candidate_history(connection, candidate_identifiers: list[str]) -> dict:
    """삭제 표시된 조합만 정리하며 빈 작업은 제거하고 공유 작업은 실제 요청 수를 갱신합니다."""

    candidate_placeholders = ",".join("?" for _ in candidate_identifiers)
    requests = connection.execute(
        "SELECT requests.request_id,requests.job_id,requests.status,jobs.origin FROM style_candidate_renders "
        "JOIN job_requests AS requests USING(request_id) JOIN jobs USING(job_id) "
        f"WHERE candidate_id IN ({candidate_placeholders})", candidate_identifiers,
    ).fetchall()
    if any(row["origin"] != "style" or row["status"] in {"submitting", "pending", "running", "cancelling"} for row in requests):
        raise ValueError("스타일 구성의 종료된 생성 요청만 정리할 수 있습니다.")
    connection.execute(f"DELETE FROM style_candidate_renders WHERE candidate_id IN ({candidate_placeholders})", candidate_identifiers)
    for request in requests:
        connection.execute("DELETE FROM output_files WHERE request_id=?", (request["request_id"],))
        connection.execute("DELETE FROM job_requests WHERE request_id=?", (request["request_id"],))
    deleted_job_identifiers = []
    retained_job_identifiers = []
    for job_identifier in sorted({row["job_id"] for row in requests}):
        request_count = connection.execute("SELECT COUNT(*) FROM job_requests WHERE job_id=?", (job_identifier,)).fetchone()[0]
        if request_count:
            connection.execute("UPDATE jobs SET request_count=? WHERE job_id=?", (request_count, job_identifier))
            retained_job_identifiers.append(job_identifier)
        else:
            connection.execute("DELETE FROM style_job_ownership WHERE job_id=?", (job_identifier,))
            connection.execute("DELETE FROM jobs WHERE job_id=? AND origin='style'", (job_identifier,))
            deleted_job_identifiers.append(job_identifier)
    return {"deletedRequestCount": len(requests), "deletedJobIdentifiers": deleted_job_identifiers,
            "retainedJobIdentifiers": retained_job_identifiers}
