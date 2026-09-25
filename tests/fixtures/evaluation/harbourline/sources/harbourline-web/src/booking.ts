// Books against a quote the shipper accepted (REQ-0001). The booking service refuses an expired
// one; this page only says so.

export async function book(quoteId: string, sailing: string): Promise<string> {
  const response = await fetch("/api/bookings", {
    method: "POST",
    body: JSON.stringify({ quote_id: quoteId, sailing }),
  });
  if (!response.ok) {
    return (await response.json()).refused;
  }
  return "booked";
}
