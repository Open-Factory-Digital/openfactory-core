// Asks the pricing service for a quote, and shows each line of it (REQ-0002).

export interface QuoteLine {
  name: string;
  amount: number;
}

export async function requestQuote(lane: [string, string], kilograms: number,
                                   volumeM3: number): Promise<QuoteLine[]> {
  const response = await fetch("/api/pricing/quote", {
    method: "POST",
    body: JSON.stringify({ lane, kilograms, volume_m3: volumeM3 }),
  });
  const lines: Record<string, number> = await response.json();
  return Object.entries(lines).map(([name, amount]) => ({ name, amount }));
}
