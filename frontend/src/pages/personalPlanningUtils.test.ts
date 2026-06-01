import { describe, expect, it, vi } from 'vitest';
import {
  buildPlanningJobs,
  buildPlanningTasks,
  horizonForDate,
  inferDomain,
  isHabitOrRoutine,
  summarizePlanning,
} from './personalPlanningUtils';
import type {
  AgentJob,
  ManagedAgent,
  MissionControlData,
} from '../lib/api';

const now = new Date('2026-05-29T12:00:00-04:00');

function job(partial: Partial<AgentJob>): AgentJob {
  return {
    id: 'job-1',
    agent_id: 'agent-1',
    name: 'Bible study reminder',
    description: '',
    job_type: 'cron',
    trigger: {},
    prompt: 'Prepare Bible study notes',
    status: 'active',
    next_run_at: now.getTime() / 1000,
    last_run_at: null,
    cooldown_seconds: 0,
    required_capabilities: [],
    approval_required_capabilities: [],
    delegation_policy: {},
    task_overrides: {},
    created_at: now.getTime() / 1000,
    updated_at: now.getTime() / 1000,
    ...partial,
  };
}

describe('personal planning utils', () => {
  it('infers life domains from task text', () => {
    expect(inferDomain('Prepare sermon notes for Sunday')).toBe('church');
    expect(inferDomain('Pay mortgage bill')).toBe('finances');
    expect(inferDomain('Workout and doctor appointment')).toBe('health');
  });

  it('maps dates into planning horizons', () => {
    expect(horizonForDate(new Date('2026-05-29T18:00:00-04:00'), now)).toBe('today');
    expect(horizonForDate(new Date('2026-06-03T09:00:00-04:00'), now)).toBe('week');
    expect(horizonForDate(new Date('2026-06-20T09:00:00-04:00'), now)).toBe('month');
    expect(horizonForDate(new Date('2026-08-01T09:00:00-04:00'), now)).toBe('long_term');
    expect(horizonForDate(null, now)).toBe('long_term');
  });

  it('builds planning tasks and excludes completed work', () => {
    const data: MissionControlData = {
      kpis: {
        projects_total: 1,
        projects_active: 1,
        projects_at_risk: 0,
        tasks_total: 2,
        tasks_in_progress: 1,
        tasks_overdue: 0,
        tasks_blocked: 0,
        tasks_done: 1,
        avg_completion: 50,
        workload_by_assignee: {},
        at_risk_projects: [],
      },
      agents: [],
      projects: [
        {
          id: 'p1',
          name: 'Church',
          status: 'Active',
          progress: 0,
          tasks: [
            {
              id: 't1',
              title: 'Sermon prep',
              status: 'In Progress',
              percent_complete: 20,
              due_date: '2026-05-29',
              linked_agents: [],
              subtasks: [],
            },
            {
              id: 't2',
              title: 'Completed task',
              status: 'Done',
              percent_complete: 100,
              linked_agents: [],
              subtasks: [],
            },
          ],
        },
      ],
    };

    const tasks = buildPlanningTasks(data);
    expect(tasks).toHaveLength(1);
    expect(tasks[0].domain).toBe('church');
  });

  it('builds jobs, detects routines, and summarizes durable items', () => {
    vi.setSystemTime(now);
    const agents = [
      { id: 'agent-1', name: 'Sermon / Study Agent' } as ManagedAgent,
    ];
    const jobs = buildPlanningJobs(agents, {
      'agent-1': [job({ id: 'job-1' })],
    });

    expect(jobs).toHaveLength(1);
    expect(jobs[0].domain).toBe('church');
    expect(isHabitOrRoutine(jobs[0])).toBe(true);
    expect(summarizePlanning([], jobs, now).activeJobs).toBe(1);
  });
});
