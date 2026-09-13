// script.js for SaiTripMaker (Advanced Multi-Agent UI)

// ✅ DOM Elements
const planForm = document.getElementById("trip-form");
const resultDiv = document.getElementById("trip-result");

// ✅ Utility: Render agent response card
function renderCard(title, content) {
    return `
        <div class="agent-card">
            <h4>${title}</h4>
            <p>${content}</p>
        </div>
    `;
}

// ✅ Handle Form Submit
planForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const destination = document.getElementById("destination").value;
    const startDate = document.getElementById("start-date").value;
    const endDate = document.getElementById("end-date").value;

    resultDiv.innerHTML = "<p>🚀 Generating your multi-agent trip plan...</p>";

    try {
        const response = await fetch("/api/plan-trip", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                destination: destination,
                start_date: startDate,
                end_date: endDate
            })
        });

        const data = await response.json();

        // ✅ Render multiple agent outputs
        let outputHTML = `
            <h3>Trip Plan for ${destination}</h3>
            ${renderCard("🗓 Itinerary", data.itinerary || "No itinerary found")}
            ${renderCard("💰 Budget", data.budget || "No budget info")}
            ${renderCard("🏨 Hotels", data.hotels || "No hotel suggestions")}
            ${renderCard("✈️ Flights", data.flights || "No flight options")}
        `;

        resultDiv.innerHTML = outputHTML;

    } catch (error) {
        console.error("Error:", error);
        resultDiv.innerHTML = "<p style='color:red;'>❌ Failed to generate trip plan.</p>";
    }
});
