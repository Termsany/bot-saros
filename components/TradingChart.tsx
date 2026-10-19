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
        const lwc: any = await import("lightweight-charts")
        if(!ref.current) return
        ref.current.innerHTML = ""
        chart = lwc.createChart(ref.current, {
          width: ref.current.clientWidth,
          height,
          layout: { background: { type: lwc.ColorType.Solid, color: "#0A0F1A" }, textColor: "#8B91A7" },
          grid: { vertLines: { color: "#232838" }, horzLines: { color: "#232838" } },
          rightPriceScale: { borderColor: "#232838" },
          timeScale: { borderColor: "#232838", timeVisible: true, secondsVisible: false },
          crosshair: { mode: 1 },
          handleScroll: true, handleScale: true,
        })
        // v5: addSeries(CandlestickSeries), v4: addCandlestickSeries
        if(typeof chart.addCandlestickSeries === "function"){
          series = chart.addCandlestickSeries({
            upColor: "#22D3A0", downColor: "#FF5470",
            borderUpColor: "#22D3A0", borderDownColor: "#FF5470",
            wickUpColor: "#22D3A0", wickDownColor: "#FF5470",
          })
        } else {
          series = chart.addSeries(lwc.CandlestickSeries, {
            upColor: "#22D3A0", downColor: "#FF5470",
            borderUpColor: "#22D3A0", borderDownColor: "#FF5470",
            wickUpColor: "#22D3A0", wickDownColor: "#FF5470",
          })
        }
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
    return <div className="h-[380px] grid place-items-center bg-void rounded-xl border border-loss/30 text-xs text-loss">خطأ الشارت: {err}</div>
  }
  if(!candles.length){
    return <div className="h-[380px] grid place-items-center bg-void rounded-xl border border-line text-xs text-muted">جاري تحميل الشموع من Binance...</div>
  }
  return <div ref={ref} className="rounded-xl border border-line overflow-hidden bg-void" style={{height}} />
}
