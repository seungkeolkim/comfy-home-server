const filesystem = require("node:fs");
const path = require("node:path");

/** 기존 Browser Fixture에 공통 작업 공간 자산과 작업 분류 읽기 API를 제공합니다. */
async function handleJobFolderReadRequest(route, jobs = []) {
  const requestUrl = new URL(route.request().url());
  const workspaceAssets = {
    "/workspace-shell.js": "text/javascript",
    "/workspace-shell.css": "text/css",
  };
  if (workspaceAssets[requestUrl.pathname]) {
    await route.fulfill({
      contentType: workspaceAssets[requestUrl.pathname],
      body: filesystem.readFileSync(path.resolve(__dirname, "..", "web", requestUrl.pathname.slice(1)), "utf8"),
    });
    return true;
  }
  let response;
  if (requestUrl.pathname === "/api/system-resources") {
    response = { status: "unavailable" };
  } else if (requestUrl.pathname === "/api/job-folders") {
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
