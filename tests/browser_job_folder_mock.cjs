/** 기존 Browser Fixture에 작업 분류 읽기 API와 이동·삭제 후보 분리를 제공합니다. */
async function handleJobFolderReadRequest(route, jobs = []) {
  const requestUrl = new URL(route.request().url());
  let response;
  if (requestUrl.pathname === "/api/job-folders") {
    response = { items: [], total_count: jobs.length, unassigned_count: jobs.length };
  } else if (requestUrl.pathname === "/api/jobs/selection-candidates") {
    const jobIdentifier = requestUrl.searchParams.get("job_id");
    const matchingJobs = jobs.filter(job => !jobIdentifier || job.job_id === jobIdentifier);
    response = {
      job_ids: matchingJobs.map(job => job.job_id),
      deletable_job_ids: matchingJobs.filter(job => !job.deletion_protected &&
        !["submitting", "pending", "running", "cancelling"].some(status =>
          job.status_counts?.[status] || job.requests?.some(request => request.status === status)))
        .map(job => job.job_id),
    };
  } else return false;
  await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  return true;
}

module.exports = { handleJobFolderReadRequest };
