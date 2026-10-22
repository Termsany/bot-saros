import { NextResponse } from "next/server"
import { paymentConfig } from "@/lib/payment-config"

export async function GET(){
  return NextResponse.json(paymentConfig())
}
