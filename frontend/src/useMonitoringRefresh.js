import { useCallback, useEffect, useRef } from 'react'
import { useOutletContext } from 'react-router-dom'

export function useMonitoringRefresh(load, acceptsEvent, minimumInterval = 0) {
  const subscribe = useOutletContext()
  const request = useRef(null)
  const refresh = useCallback(() => request.current?.(), [])

  useEffect(() => {
    let active = true
    let running = false
    let pending = false
    let timer = null
    let poll = null
    let lastStarted = 0

    function requestRefresh() {
      pending = true
      if (active && !running && timer === null) {
        timer = setTimeout(refresh, Math.max(75, minimumInterval - (Date.now() - lastStarted)))
      }
    }

    async function refresh() {
      timer = null
      lastStarted = Date.now()
      running = true
      pending = false
      try {
        await load(() => active)
      } finally {
        running = false
        if (pending) requestRefresh()
      }
    }

    const unsubscribe = subscribe((event) => {
      if (event?.type === 'monitoring.connection') {
        if (event.healthy) {
          clearInterval(poll)
          poll = null
        } else if (poll === null) {
          poll = setInterval(requestRefresh, 30_000)
        }
        return
      }
      if (!acceptsEvent || acceptsEvent(event)) requestRefresh()
    })
    request.current = requestRefresh
    refresh()
    return () => {
      active = false
      request.current = null
      unsubscribe()
      clearTimeout(timer)
      clearInterval(poll)
    }
  }, [load, subscribe, acceptsEvent, minimumInterval])
  return refresh
}
