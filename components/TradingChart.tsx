"use client"
import { useEffect, useRef, useState } from "react"

type Candle = { time: number; open: number; high: number; low: number; close: number }
type Marker = { time: number; position: "aboveBar"|"belowBar"; color: string; shape: "arrowUp"|"arrowDown"|"circle"; text: string }

export function TradingChart({ candles, markers, height=380 }: { candles: Candle[]; markers?: Marker[]; height?: number }){
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<any>(null)
  const [err, setErr] = useState("")

  useEffect(()=>{
    if(!ref.current) return
    if(!candles.length){
      setErr("")
      return
    }
    let chart: any = null
    let series: any = null
    let ro: ResizeObserver | null = null

    async function init(){
      try{
        const { createChart, ColorType } = await import("lightweight-charts")
        if(!ref.current) return
        ref.current.innerHTML = ""
        chart = createChart(ref.current, {
          width: ref.current.clientWidth,
          height,
          layout: { background: { type: ColorType.Solid, color: "#0A0F1A" }, textColor: "#8A9AB0" },
          grid: { vertLines: { color: "#1E2A3A" }, horzLines: { color: "#1E2A3A" } },
          rightPriceScale: { borderColor: "#1E2A3A" },
          timeScale: { borderColor: "#1E2A3A", timeVisible: true, secondsVisible: false },
          crosshair: { mode: 1 },
          handleScroll: true, handleScale: true,
        })
        series = chart.addCandlestickSeries({
          upColor: "#00D395", downColor: "#FF3B5C",
          borderUpColor: "#00D395", borderDownColor: "#FF3B5C",
          wickUpColor: "#00D395", wickDownColor: "#FF3B5C",
        })
        // Ensure sorted ascending
        const sorted = [...candles].sort((a,b)=> a.time - b.time)
        series.setData(sorted)
        if(markers?.length){
          try{ series.setMarkers(markers) }catch{}
        }
        chart.timeScale().fitContent()
        ro = new ResizeObserver(()=>{
          if(ref.current && chart) chart.applyOptions({ width: ref.current.clientWidth })
        })
        ro.observe(ref.current!)
        chartRef.current = { chart, ro }
        setErr("")
      }catch(e:any){
        setErr(String(e?.message||e))
      }
    }
    init()
    return ()=>{
      try{ ro?.disconnect(); chart?.remove() }catch{}
    }
  }, [candles, markers, height])

  if(err){
    return <div className="h-[380px] grid place-items-center bg-[#0A0F1A] rounded-xl border border-[#FF3B5C]/30 text-xs text-[#FF3B5C]">خطأ الشارت: {err}</div>
  }
  if(!candles.length){
    return <div className="h-[380px] grid place-items-center bg-[#0A0F1A] rounded-xl border border-[#1E2A3A] text-xs text-[#8A9AB0]">جاري تحميل الشموع من Binance...</div>
  }
  return <div ref={ref} className="rounded-xl border border-[#1E2A3A] overflow-hidden bg-[#0A0F1A]" style={{height}} />
}
