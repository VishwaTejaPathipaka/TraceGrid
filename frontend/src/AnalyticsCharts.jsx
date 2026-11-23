import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getAnalyticsChecks } from './api'
import {
  bucketDescription, bucketTone, comparisonLabel, durationLabel, latencyPlot, metrics, ranges, sampleDescription, timeLabel, timelineBucket,
} from './analyticsDisplay'
import { checkedTime, count, latency, probeStatusLabel } from './monitoringDisplay'
import { EmptyState } from './MonitoringUI'

export function RangeControl({ range, onChange }) {
  return <div className="range-control" role="group" aria-label="Analytics time range">
    {Object.entries(ranges).map(([key, label]) => <button className="button small" type="button" key={key}
      aria-pressed={range === key} onClick={() => onChange(key)}>{label}</button>)}
  </div>
}

function TimeAxis({ start, span }) {
  return <div className="analytics-time-axis mono" aria-hidden="true">
    {[0, .5, 1].map((fraction) => <span key={fraction}>{timeLabel(start + span * fraction, span)}</span>)}
  </div>
}

function ChartTitle({ title, detail }) {
  return <header className="section-head"><div><h2>{title}</h2>{detail && <p>{detail}</p>}</div></header>
}

export function ResponseTrend({ points, statistics, window, gap }) {
  const [selected, setSelected] = useState(null)
  if (!points.length) return <section className="surface analytics-panel">
    <ChartTitle title="Response-time trend" /><EmptyState title="No measured response times">Monitoring errors are excluded from latency.</EmptyState>
  </section>
  const { samples, segments, maximum, start, span } = latencyPlot(points, window)
  const index = samples.findIndex((point) => point.id === selected)
  const current = samples[index >= 0 ? index : samples.length - 1]
  const maxPointCount = samples.length
  const hasFailure = samples.some((point) => point.status !== 'UP')
  const hasSpikeLevel = statistics.p95 != null && statistics.maximum > statistics.median
  function inspect(event) {
    const box = event.currentTarget.getBoundingClientRect()
    const x = (event.clientX - box.left) / box.width
    const y = (event.clientY - box.top) / box.height
    const nearest = samples.reduce((best, point) => {
      const distance = (candidate) => Math.abs(candidate.x - x) + Math.abs(candidate.y - y) * .02
      return distance(point) < distance(best) ? point : best
    })
    setSelected(nearest.id)
  }
  return <section className="surface analytics-panel">
    <ChartTitle title="Response-time trend" detail={`${count(statistics.samples)} measured samples · Local time · Milliseconds`} />
    <div className="analytics-chart-body">
      <div className="latency-figure">
        <div className="latency-axis mono" aria-hidden="true">{[1, .75, .5, .25, 0].map((step) =>
          <span key={step}>{latency(maximum * step)}</span>)}</div>
        <div className="latency-plot" onPointerMove={inspect} onPointerDown={inspect}>
          <svg viewBox="0 0 600 210" preserveAspectRatio="none" aria-hidden="true">
            {[0, .25, .5, .75, 1].map((line) => <line className="chart-gridline" key={line} x1="0" x2="600" y1={line * 210} y2={line * 210} />)}
            {segments.filter((segment) => segment.length > 1).map((segment) =>
              <polyline className="latency-line" key={segment[0].id} points={segment.map(({ x, y }) => `${x * 600},${y * 210}`).join(' ')} />)}
          </svg>
          {samples.map((point) => {
            const spike = hasSpikeLevel && point.status === 'UP' && point.response_time >= statistics.p95 &&
              point.response_time > statistics.median
            return <span key={point.id} className={`latency-dot ${point.status !== 'UP' ? 'latency-failure' : spike ? 'latency-spike' : ''} ${point.id === current.id ? 'latency-selected' : ''}`}
              aria-hidden="true" style={{ left: `${point.x * 100}%`, top: `${point.y * 100}%` }} />
          })}
        </div>
        <span aria-hidden="true" />
        <TimeAxis start={start} span={span} />
      </div>
      <label className="latency-scrubber">Inspect plotted check
        <input type="range" min="0" max={maxPointCount - 1} value={index >= 0 ? index : maxPointCount - 1}
          disabled={maxPointCount === 1} aria-valuetext={sampleDescription(current)}
          onChange={(event) => setSelected(samples[Number(event.target.value)].id)} />
      </label>
      <p className="analytics-readout mono">{sampleDescription(current)}</p>
      <p className="analytics-caption">Lines join successful checks only and break at failures, monitoring errors, or gaps over {gap} seconds.
        {hasFailure && ' × marks unsuccessful checks.'}{hasSpikeLevel && ' Outlined points are successful checks at or above the window p95 and above the median.'}
        {statistics.samples > points.length && ` Showing ${count(points.length)} representative checks, including bucket extrema.`}
      </p>
    </div>
  </section>
}

function BucketChecks({ endpointId, range, selection }) {
  const [cursors, setCursors] = useState([null])
  const [report, setReport] = useState(null)
  const cursor = cursors.at(-1)
  const key = cursor ? `${cursor.at}:${cursor.id}` : 'first'
  useEffect(() => {
    if (!selection.hasChecks) return
    let active = true
    getAnalyticsChecks(localStorage.getItem('access_token'), endpointId, range, selection.window.end, selection.index, cursor)
      .then((data) => { if (active) setReport({ key, data }) }, (error) => { if (active) setReport({ key, error: error.message }) })
    return () => { active = false }
  }, [endpointId, range, selection, cursor, key])
  const result = report?.key === key ? report : null
  const { start, end } = timelineBucket(selection.window, selection.index)
  return <div className="analytics-interval">
    <h3>Individual checks</h3>
    <p className="analytics-caption mono">{checkedTime(start)} – {checkedTime(end)} · Start included, end excluded</p>
    {!selection.hasChecks && <p className="analytics-caption">No checks recorded in this interval.</p>}
    {selection.hasChecks && !result && <p className="analytics-caption" role="status">Loading checks…</p>}
    {result?.error && <p className="notice notice-error" role="alert">{result.error}</p>}
    {result?.data && <>
      <ol className="analytics-checks">{result.data.items.map((sample) => <li key={sample.id}>
        <time dateTime={sample.checked_at} className="mono">{checkedTime(sample.checked_at)}</time>
        <strong className={['DOWN', 'REDIRECT'].includes(sample.status) ? 'error-text' : undefined}>{probeStatusLabel(sample)}</strong>
        <span className="mono">{sample.status_code == null ? '—' : `HTTP ${sample.status_code}`}</span>
        <span className="mono">{sample.status === 'ERROR' && sample.response_time != null ? 'Probe ' : ''}{latency(sample.response_time)}</span>
      </li>)}</ol>
      {(cursors.length > 1 || result.data.next_cursor) && <div className="button-row analytics-check-paging">
        <button className="button small" type="button" disabled={cursors.length === 1} onClick={() => setCursors(cursors.slice(0, -1))}>Previous checks</button>
        <button className="button small" type="button" disabled={!result.data.next_cursor} onClick={() => setCursors([...cursors, result.data.next_cursor])}>Next checks</button>
      </div>}
    </>}
  </div>
}

export function AvailabilityTimeline({ endpointId, range, window, buckets, gap }) {
  const [selected, setSelected] = useState(null)
  const [focused, setFocused] = useState(null)
  const entries = new Map(buckets.map((bucket) => [bucket.index, bucket]))
  const start = Date.parse(window.start)
  const span = Date.parse(window.end) - start
  const focusIndex = focused ?? window.bucket_count - 1
  function moveFocus(event, index) {
    const targets = { ArrowLeft: index - 1, ArrowRight: index + 1, Home: 0, End: window.bucket_count - 1 }
    if (!(event.key in targets)) return
    event.preventDefault()
    const target = Math.max(0, Math.min(window.bucket_count - 1, targets[event.key]))
    setFocused(target)
    event.currentTarget.parentElement.children[target]?.focus()
  }
  return <section className="surface analytics-panel">
    <ChartTitle title="Availability timeline" detail="Select an interval to see individual checks in recorded order." />
    <div className="analytics-chart-body">
      <div className="timeline-scroll">
        <div className="timeline-track" style={{ '--bucket-count': window.bucket_count }}>
          {Array.from({ length: window.bucket_count }, (_, index) => {
            const bucket = entries.get(index)
            const { start, end } = timelineBucket(window, index)
            const [tone, mark, mixed] = bucketTone(bucket)
            const label = `${checkedTime(start)} to ${checkedTime(end)}. ${bucketDescription(bucket)}`
            const isSelected = selected?.index === index && selected.window.end === window.end
            return <button type="button" key={index} tabIndex={index === focusIndex ? 0 : -1} aria-pressed={isSelected}
              aria-label={label} title={label} className={`timeline-segment timeline-${tone} ${mixed ? 'timeline-mixed' : ''}`}
              onFocus={() => setFocused(index)} onKeyDown={(event) => moveFocus(event, index)}
              onClick={() => setSelected({ index, window, hasChecks: Boolean(bucket) })}>{mark}</button>
          })}
        </div>
      </div>
      <TimeAxis start={start} span={span} />
      <p className="analytics-caption timeline-legend">• Successful · <span className="error-text">× Unsuccessful</span> · ? Monitoring error · – No checks · Dashed edge: mixed results or a gap over {gap} s</p>
      {selected && <BucketChecks key={`${selected.window.end}:${selected.index}`} endpointId={endpointId} range={range} selection={selected} />}
      {!buckets.length && <p className="analytics-caption">No monitoring results in this window.</p>}
    </div>
  </section>
}

export function LatencyHistogram({ statistics, histogram }) {
  const n = statistics.samples
  const maximum = Math.max(...histogram.map((bin) => bin.count), 1)
  return <section className="surface analytics-panel">
    <ChartTitle title="Response-time distribution" detail={`${count(n)} measured availability checks · Milliseconds`} />
    {!n ? <EmptyState title="No measured response times" /> : <div className="analytics-chart-body">
      <dl className="analytics-ledger analytics-distribution">
        {[['Average', statistics.average], ['Median', statistics.median], ['p95', statistics.p95], ['p99', statistics.p99], ['Maximum', statistics.maximum]].map(([label, value]) =>
          <div key={label}><dt>{label}</dt><dd>{value == null ? '—' : latency(value)}</dd></div>)}
      </dl>
      <ul className="analytics-bars" aria-label="Latency bins and sample counts">
        {histogram.map((bin) => {
          const label = bin.upper == null ? `≥ ${count(bin.lower)} ms` : `${count(bin.lower)} to <${count(bin.upper)} ms`
          return <li key={bin.lower} className="histogram-row"><span className="mono">{label}</span>
            <span className="analytics-bar-track" aria-hidden="true"><span style={{ width: `${bin.count / maximum * 100}%` }} /></span>
            <strong className="mono">{count(bin.count)}</strong></li>
        })}
      </ul>
      <p className="analytics-caption">Bars start at zero and represent check counts. The last bin includes all slower checks.
        {n < 100 && ' Minimum samples: median 2, p95 20, p99 100.'}</p>
    </div>}
  </section>
}

export function EndpointAnalysis({ endpoint, window, range }) {
  const { latency: statistics, availability } = endpoint
  return <div className="analytics-track">
    <dl className="analytics-ledger analytics-availability">
      <div><dt>Uptime</dt><dd>{comparisonLabel(endpoint.uptime, 'uptime')}</dd></div>
      <div><dt>Successful</dt><dd>{count(availability.successful)}</dd></div>
      <div><dt>Unsuccessful</dt><dd className={availability.unsuccessful ? 'error-text' : undefined}>{count(availability.unsuccessful)}</dd></div>
      <div><dt>Monitoring errors</dt><dd>{count(availability.monitoring_errors)}</dd></div>
    </dl>
    <ResponseTrend points={endpoint.trend} statistics={statistics} window={window} gap={endpoint.gap_seconds} />
    <AvailabilityTimeline endpointId={endpoint.id} range={range} window={window} buckets={endpoint.timeline} gap={endpoint.gap_seconds} />
    <LatencyHistogram statistics={statistics} histogram={endpoint.histogram} />
  </div>
}

export function EndpointComparison({ comparison, metric, descending, onMetric, onDirection, onPage, range }) {
  const maximum = metric === 'uptime' ? 100 : comparison?.maximum ?? 0
  return <section className="surface analytics-panel">
    <ChartTitle title="Endpoint comparison" detail="All owned endpoints · Same time range" />
    {comparison && comparison.total < 2 ? <EmptyState title={comparison.total ? 'Only one endpoint' : 'No endpoints to compare'}>
      Add another endpoint to compare performance and reliability.
    </EmptyState> : <div className="analytics-chart-body">
      <div className="analytics-controls">
        <label>Metric<select value={metric} onChange={(event) => onMetric(event.target.value)}>
          {Object.entries(metrics).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
        </select></label>
        <label>Sort<select value={descending ? 'desc' : 'asc'} onChange={(event) => onDirection(event.target.value === 'desc')}>
          <option value="desc">Highest first</option><option value="asc">Lowest first</option>
        </select></label>
      </div>
      {comparison && <>
        <ul className="analytics-bars" aria-label="Endpoint comparison">
          {comparison.items.map((row) => <li key={row.id} className="comparison-row">
            <div><Link to={`/analytics?endpoint=${row.id}&range=${range}`}>{row.name}</Link><p>{count(row.samples)} samples</p></div>
            <span className={`analytics-bar-track ${row.value == null ? 'analytics-bar-empty' : ''}`} aria-hidden="true">
              {row.value != null && <span className={metric === 'unsuccessful' ? 'analytics-bar-failed' : undefined}
                style={{ width: `${maximum ? row.value / maximum * 100 : 0}%` }} />}
            </span>
            <strong className="mono">{comparisonLabel(row.value, metric)}</strong>
          </li>)}
        </ul>
        {!!maximum && <p className="analytics-caption">Scale: {comparisonLabel(0, metric)} to {comparisonLabel(maximum, metric)}</p>}
        {(comparison.offset > 0 || comparison.total > comparison.limit) && <div className="pagination analytics-pagination">
          <span className="mono">{comparison.items.length ? `${comparison.offset + 1}–${comparison.offset + comparison.items.length} of ${count(comparison.total)}` : 'No endpoints on this page'}</span>
          <div className="button-row">
            <button className="button small" disabled={!comparison.offset} onClick={() => onPage(Math.max(0, comparison.offset - comparison.limit))}>Previous</button>
            <button className="button small" disabled={comparison.offset + comparison.limit >= comparison.total} onClick={() => onPage(comparison.offset + comparison.limit)}>Next</button>
          </div>
        </div>}
      </>}
    </div>}
  </section>
}

export function IncidentAnalytics({ report }) {
  return <section className="surface analytics-panel">
    <ChartTitle title="Incident activity" detail="Opened and resolved counts use their transition timestamps." />
    {!report.overlapping && !report.opened && !report.recovered && !report.manually_resolved ?
      <EmptyState title="No incident activity in this window" /> :
      <div className="analytics-chart-body">
        <dl className="analytics-ledger analytics-distribution">
          <div><dt>Active during window</dt><dd>{count(report.overlapping)}</dd></div>
          <div><dt>Opened</dt><dd>{count(report.opened)}</dd></div>
          <div><dt>Automatically recovered</dt><dd>{count(report.recovered)}</dd></div>
          <div><dt>Manually resolved</dt><dd>{count(report.manually_resolved)}</dd></div>
          <div><dt>Average recovery</dt><dd>{durationLabel(report.average_recovery_seconds)}</dd></div>
        </dl>
        <p className="analytics-caption">Active during window includes incidents that began before it. Average recovery measures first failure to successful check for automatic recoveries only.</p>
        {!!report.affected.length && <div className="analytics-affected"><h3>Most frequently affected endpoints</h3>
          <ul>{report.affected.map((endpoint) => <li key={endpoint.id ?? endpoint.name}>
            <span>{endpoint.name}</span><strong className="mono">{count(endpoint.incidents)} {endpoint.incidents === 1 ? 'incident' : 'incidents'}</strong>
          </li>)}</ul>
        </div>}
      </div>}
  </section>
}
