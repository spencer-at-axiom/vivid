import type { Job } from "../lib/types";
import type { QueueState } from "../lib/types";
import { cancelJob, clearQueue, pauseQueue, resumeQueue, retryJob, reorderQueue } from "../lib/api";

export interface QueueStatusProps {
  jobs: Job[];
  queueState: QueueState;
  onQueueStateChanged: (state: QueueState) => void;
  onJobUpdated: (job: Job) => void;
  onQueueCleared: () => void;
  onJobRetried: (job: Job) => void;
}

export default function QueueStatus({
  jobs,
  queueState,
  onQueueStateChanged,
  onJobUpdated,
  onQueueCleared,
  onJobRetried,
}: QueueStatusProps) {
  type CurrentJobView = {
    id: string;
    kind: string;
    status: "running" | "cancel_requested";
    progress: number;
    eta_seconds?: number | null;
    eta_confidence?: "none" | "low" | "high";
    warnings?: string[];
  };
  const jobById = new Map(jobs.map((job) => [job.id, job]));
  const activeJobs = jobs.filter(
    (job) =>
      job.status === "running" ||
      job.status === "cancel_requested" ||
      job.status === "queued" ||
      job.status === "recovered"
  );
  const fallbackQueuedIds = jobs
    .filter((job) => job.status === "queued" || job.status === "recovered")
    .map((job) => job.id);
  const effectiveQueuedIds = queueState.queued_job_ids.length > 0 ? queueState.queued_job_ids : fallbackQueuedIds;
  const queuedJobs = effectiveQueuedIds
    .map((jobId) => jobById.get(jobId))
    .filter((job): job is Job => Boolean(job));
  const currentJobFromList =
    (queueState.running_job_id ? jobById.get(queueState.running_job_id) : null) ??
    activeJobs.find((job) => job.status === "running" || job.status === "cancel_requested");
  const currentJob: CurrentJobView | null = currentJobFromList
    ? {
        id: currentJobFromList.id,
        kind: currentJobFromList.kind,
        status: currentJobFromList.status === "cancel_requested" ? "cancel_requested" : "running",
        progress: currentJobFromList.progress,
        eta_seconds: currentJobFromList.eta_seconds,
        eta_confidence: currentJobFromList.eta_confidence,
        warnings: currentJobFromList.warnings,
      }
    : queueState.active_job
    ? {
        id: queueState.active_job.id,
        kind: queueState.active_job.kind,
        status: queueState.active_job.status,
        progress: queueState.active_job.progress,
        eta_seconds: queueState.active_job.eta_seconds,
        eta_confidence: queueState.active_job.eta_confidence,
        warnings: [],
      }
    : null;
  const latestRetriable = jobs.find((job) => job.status === "failed" || job.status === "cancelled");
  const latestRuntimeNotice =
    currentJob?.warnings?.[0] ??
    jobs.find((job) => Array.isArray(job.warnings) && job.warnings.length > 0)?.warnings?.[0] ??
    null;
  const queuedCount = Math.max(queueState.queued_count ?? 0, queuedJobs.length);
  const showEta =
    currentJob?.eta_confidence === "high" &&
    typeof currentJob.eta_seconds === "number" &&
    currentJob.eta_seconds > 0;

  const handleCancel = async (jobId: string) => {
    try {
      const updated = await cancelJob(jobId);
      onJobUpdated(updated);
    } catch (error) {
      console.error("Failed to cancel job:", error);
    }
  };

  const handleTogglePause = async () => {
    try {
      if (queueState.paused) {
        const state = await resumeQueue();
        onQueueStateChanged(state);
      } else {
        const state = await pauseQueue();
        onQueueStateChanged(state);
      }
    } catch (error) {
      console.error("Failed to update queue pause state:", error);
    }
  };

  const handleClear = async () => {
    try {
      const state = await clearQueue(false);
      onQueueStateChanged(state);
      onQueueCleared();
    } catch (error) {
      console.error("Failed to clear queue:", error);
    }
  };

  const handleRetry = async () => {
    if (!latestRetriable) return;
    try {
      const retried = await retryJob(latestRetriable.id);
      onJobRetried(retried);
    } catch (error) {
      console.error("Failed to retry job:", error);
    }
  };

  const handleMoveQueuedJob = async (jobId: string, direction: "up" | "down") => {
    const currentIndex = effectiveQueuedIds.indexOf(jobId);
    if (currentIndex < 0) return;
    const nextIndex = direction === "up" ? currentIndex - 1 : currentIndex + 1;
    if (nextIndex < 0 || nextIndex >= effectiveQueuedIds.length) return;

    const reordered = [...effectiveQueuedIds];
    const [moved] = reordered.splice(currentIndex, 1);
    reordered.splice(nextIndex, 0, moved);

    try {
      const updatedState = await reorderQueue(reordered);
      onQueueStateChanged(updatedState);
    } catch (error) {
      console.error("Failed to reorder queue:", error);
    }
  };

  if (!currentJob && queuedCount === 0 && !queueState.paused && !latestRetriable) {
    return null;
  }

  return (
    <div className="queue-status">
      {currentJob && (
        <div className="current-job">
          <div className="job-info">
            <span className="job-kind">{currentJob.kind}</span>
            <span className="job-progress">{Math.round(currentJob.progress * 100)}%</span>
            {currentJob.status === "cancel_requested" && <span className="job-eta">cancelling...</span>}
            {showEta && (
              <span className="job-eta">~{currentJob.eta_seconds}s</span>
            )}
          </div>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${currentJob.progress * 100}%` }} />
          </div>
          <button
            className="cancel-btn"
            onClick={() => handleCancel(currentJob.id)}
            disabled={currentJob.status === "cancel_requested"}
            type="button"
          >
            {currentJob.status === "cancel_requested" ? "Cancelling..." : "Cancel"}
          </button>
        </div>
      )}

      <div className="queue-actions-inline">
        <button className="queue-action-btn" onClick={handleTogglePause} type="button">
          {queueState.paused ? "Resume Queue" : "Pause Queue"}
        </button>
        {queuedCount > 0 && (
          <button className="queue-action-btn" onClick={handleClear} type="button">
            Clear Queued
          </button>
        )}
        {latestRetriable && (
          <button className="queue-action-btn" onClick={handleRetry} type="button">
            Retry Last
          </button>
        )}
      </div>

      {queueState.paused && <div className="queue-count">Queue paused</div>}
      {queuedCount > 0 && <div className="queue-count">Queued: {queuedCount}</div>}
      {latestRuntimeNotice && <div className="queue-count">{latestRuntimeNotice}</div>}

      {queuedJobs.length > 1 && (
        <div className="queue-reorder">
          <span className="queue-label">Queued</span>
          <ul className="queue-reorder-list">
            {queuedJobs.slice(0, 4).map((job, index) => (
              <li key={job.id} className="queue-reorder-item">
                <span className="queue-reorder-name">{job.kind}</span>
                <div className="queue-reorder-actions">
                  <button
                    className="queue-action-btn"
                    onClick={() => handleMoveQueuedJob(job.id, "up")}
                    disabled={index === 0}
                    type="button"
                    title="Move up"
                  >
                    Up
                  </button>
                  <button
                    className="queue-action-btn"
                    onClick={() => handleMoveQueuedJob(job.id, "down")}
                    disabled={index === queuedJobs.length - 1}
                    type="button"
                    title="Move down"
                  >
                    Down
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
