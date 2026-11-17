// The table lives in the Python package (python/agent_xray/pricing.json) and is bundled here.
import table from '../../../python/agent_xray/pricing.json'
import type { ModelUsage } from './reducer'

interface Price {
  input: number
  output: number
}

const PRICES = new Map<string, Price>(Object.entries(table.models as Record<string, Price>))
const PER = table.per_tokens

/** Price of a model name, or null when it is not in the table. */
export function priceFor(model: string, prices: ReadonlyMap<string, Price> = PRICES): Price | null {
  // "models/gemini-2.0-flash", "accounts/x/models/llama-...": keep the last path segment
  const name = (model.split('/').at(-1) ?? model).toLowerCase()
  const exact = prices.get(name)
  if (exact) return exact
  let best: string | null = null
  for (const key of prices.keys()) {
    if ((name.startsWith(key) || name.includes(key)) && (best === null || key.length > best.length))
      best = key
  }
  return best ? (prices.get(best) ?? null) : null
}

export interface CostEstimate {
  usd: number
  /** Models that were used but have no price, so the total excludes them. */
  unpriced: string[]
}

export function equivalentCost(
  byModel: ReadonlyMap<string, ModelUsage>,
  prices?: ReadonlyMap<string, Price>,
): CostEstimate {
  let usd = 0
  const unpriced: string[] = []
  for (const [model, usage] of byModel) {
    const price = priceFor(model, prices)
    if (!price) {
      unpriced.push(model)
      continue
    }
    usd += (usage.inputTokens * price.input + usage.outputTokens * price.output) / PER
  }
  return { usd, unpriced }
}

export function formatUsd(usd: number): string {
  if (usd === 0) return '$0.00'
  if (usd < 0.0001) return '<$0.0001'
  if (usd < 0.01) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(usd < 1 ? 3 : 2)}`
}
