"use client"
import { useEffect, useRef } from "react"

type Candle = { time: number; open: number; high: number; low: number; close: number }
type Marker = { time: number; position: "aboveBar"|"belowBar"; color: string; shape: "arrowUp"|"arrowDown"|"circle"; text: string }

export function TradingChart({ candles, markers, height=360 }: { candles: Candle[]; markers?: Marker[]; height?: number }){
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<any>(null)

  useEffect(()=>{
    if(!ref.current || !candles.length) return
    let chart: any = null
    let series: any = null

    async function init(){
      const { createChart, ColorType } = await import("lightweight-charts")
      if(!ref.current) return
      // cleanup old
      ref.current.innerHTML = ""
      chart = createChart(ref.current, {
        width: ref.current.clientWidth,
        height,
        layout: { background: { type: ColorType.Solid, color: "#0A0F1A" }, textColor: "#8A9AB0" },
        grid: { vertLines: { color: "#1E2A3A" }, horzLines: { color: "#1E2A3A" } },
        rightPriceScale: { borderColor: "#1E2A3A" },
        timeScale: { borderColor: "#1E2A3A", timeVisible: true },
        crosshair: { mode: 1 },
      })
      series = chart.addCandlestickSeries({
        upColor: "#00D395", downColor: "#FF3B5C",
        borderUpColor: "#00D395", borderDownColor: "#FF3B5C",
        wickUpColor: "#00D395", wickDownColor: "#FF3B5C",
      })
      series.setData(candles)
      if(markers?.length){
        try{ series.setMarkers(markers) }catch{}
      }
      chart.timeScale().fitContent()

      const ro = new ResizeObserver(()=>{
        if(ref.current && chart) chart.applyOptions({ width: ref.current.clientWidth })
      })
      ro.observe(ref.current!)
      chartRef.current = { chart, ro }
    }
    init()
    return ()=>{
      try{ chartRef.current?.ro?.disconnect(); chartRef.current?.chart?.remove() }catch{}
    }
  }, [candles, markers, height])

  if(!candles.length){
    return <div className="h-[360px] grid place-items-center bg-[#0A0F1A] rounded-xl border border-[#1E2A3A] text-xs text-[#8A9AB0]">جاري تحميل الشموع...</div>
  }
  return <div ref={ref} className="rounded-xl border border-[#1E2A3A] overflow-hidden" style={{height}} />
}
