import { useCallback, useState } from 'react'
import { getAnalyticsReport } from './api'
import { useMonitoringRefresh } from './useMonitoringRefresh'

export function useAnalyticsReport({ endpointId, range, compare, metric = 'uptime', descending = true, offset = 0 }) {
  const key = `${endpointId}:${range}:${compare}:${metric}:${descending}:${offset}`
  const [result, setResult] = useState(null)
  const load = useCallback(async (isActive) => {
    try {
      const data = await getAnalyticsReport(localStorage.getItem('access_token'), { endpointId, range, compare, metric, descending, offset })
      if (isActive()) setResult({ key, data, error: '' })
    } catch (err) {
      if (isActive()) setResult((previous) => ({ key, data: previous?.key === key ? previous.data : null, error: err.message }))
    }
  }, [key, endpointId, range, compare, metric, descending, offset])
  const accepts = useCallback((event) => compare || !event?.endpoint_id || event.endpoint_id === endpointId, [compare, endpointId])
  const refresh = useMonitoringRefresh(load, accepts, 5000)
  return { data: result?.key === key ? result.data : null, error: result?.key === key ? result.error : '', refresh }
}
