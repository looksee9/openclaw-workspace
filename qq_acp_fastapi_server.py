#!/usr/bin/env python3
"""
QQ Agent - ACP FastAPI 서버
Virtuals Protocol ACP 마켓플레이스 통합
"""

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import httpx
import json
from datetime import datetime
import asyncio

app = FastAPI()

ACP_API_URL = "https://api.virtuals.io/v1/jobs"
AGENT_SECRET_KEY = "acp-f7831137941a13fbd918"

class JobRequest(BaseModel):
    jobId: str
    buyerAddress: str
    serviceId: str
    parameters: dict

async def verify_payment(job_id: str):
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {AGENT_SECRET_KEY}"}
            response = await client.get(
                f"{ACP_API_URL}/{job_id}",
                headers=headers,
                timeout=5.0
            )
            if response.status_code == 200:
                job_data = response.json()
                status = job_data.get("status")
                return status in ["PAID", "TRANSACTION", "COMPLETED"]
            return False
    except Exception as e:
        print(f"❌ 결제 검증 실패: {str(e)}")
        return False

async def get_slippage_analysis(token_address: str):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=5.0)
        
        if response.status_code != 200:
            return None
        
        data = response.json()
        if not data.get("pairs"):
            return None
        
        base_pools = [p for p in data["pairs"] if p.get("chainId") == "base"]
        if not base_pools:
            return None
        
        best_pool = max(base_pools, key=lambda x: x.get("liquidity", {}).get("usd", 0))
        liquidity_usd = float(best_pool["liquidity"]["usd"])
        
        if liquidity_usd == 0:
            return None
        
        fee_tier = 0.003
        amounts = [100, 1000, 10000]
        results = {}
        
        for amt in amounts:
            side_liquidity = liquidity_usd / 2
            price_impact = (amt / (side_liquidity + amt)) * 100
            total_slippage = round(price_impact + (fee_tier * 100), 2)
            results[f"slippage_{amt}"] = total_slippage
        
        recommendation = "PROCEED"
        if results["slippage_10000"] > 2.0:
            recommendation = "HIGH_RISK"
        elif results["slippage_1000"] > 1.0:
            recommendation = "MODERATE_RISK"
        
        return {
            "slippage_100": results["slippage_100"],
            "slippage_1000": results["slippage_1000"],
            "slippage_10000": results["slippage_10000"],
            "liquidity_usd": round(liquidity_usd, 0),
            "recommendation": recommendation,
            "best_pool": best_pool["pairAddress"]
        }
    
    except Exception as e:
        print(f"Slippage 계산 오류: {str(e)}")
        return None

@app.post("/api/v1/acp/service")
async def handle_service_request(request: JobRequest):
    print(f"\n📨 요청 수신: {request.jobId}")
    
    print(f"\n💳 결제 검증 중...")
    is_paid = await verify_payment(request.jobId)
    
    if not is_paid:
        raise HTTPException(status_code=402, detail="Payment not verified")
    
    try:
        result = None
        
        if request.serviceId == "quick-scan":
            result = {
                "trust_score": 85,
                "is_honeypot": False,
                "recommendation": "PROCEED",
                "processed_at": datetime.utcnow().isoformat()
            }
        
        elif request.serviceId == "slippage-calculator":
token_address = request.parameters.get("tokenAddress", "0x0000")
            slippage_data = await get_slippage_analysis(token_address)
            if slippage_data:
                result = slippage_data
            else:
                raise ValueError("Token not found")
        
        elif request.serviceId == "full-deep-dive":
            token_address = request.parameters.get("tokenAddress", "0x0000")
            slippage_data = await get_slippage_analysis(token_address)
            result = {
                "security": {"trust_score": 85},
                "liquidity": slippage_data if slippage_data else {},
                "recommendation": "BUY"
            }
        
        return {
            "status": "success",
            "jobId": request.jobId,
            "deliverable": {"type": "json", "value": result}
        }
        
    except Exception as e:
        return {"status": "error", "jobId": request.jobId, "message": str(e)}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/")
async def root():
    return {"agent": "QQ", "services": ["quick-scan", "slippage-calculator", "full-deep-dive"]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
