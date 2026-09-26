async function updateDashboard() {
    try {
        const response = await fetch("/status");

        if (!response.ok) {
            throw new Error(`Status request failed: ${response.status}`);
        }

        const data = await response.json();

        updateStats(data);
        updateParkingSpaces(data);
        updateLastUpdated();

    } catch (error) {
        console.error("Dashboard error:", error);
    }
}


function updateStats(data) {
    const capacityElement = document.getElementById("capacity");
    const occupiedElement = document.getElementById("occupied");
    const availableElement = document.getElementById("available");

    if (capacityElement) {
        capacityElement.textContent = data.capacity;
    }

    if (occupiedElement) {
        occupiedElement.textContent = data.occupied;
    }

    if (availableElement) {
        availableElement.textContent = data.available;
    }
}


function updateParkingSpaces(data) {
    const container = document.getElementById("parking-spaces");

    if (!container || !data.spaces) {
        return;
    }

    container.innerHTML = "";

    Object.entries(data.spaces).forEach(([space, occupied]) => {
        const element = document.createElement("div");

        element.className = occupied
            ? "parking-space occupied"
            : "parking-space available";

        element.innerHTML = `
            <span class="space-name">${space}</span>
            <span class="space-status">
                ${occupied ? "Occupied" : "Available"}
            </span>
        `;

        container.appendChild(element);
    });
}


function updateLastUpdated() {
    const element = document.getElementById("last-updated");

    if (!element) {
        return;
    }

    element.textContent =
        `Last updated: ${new Date().toLocaleTimeString()}`;
}


// ------------------------------------------
// Historical occupancy
// ------------------------------------------

async function loadHistory() {
    try {
        const response = await fetch("/history?limit=100");

        if (!response.ok) {
            throw new Error(
                `History request failed: ${response.status}`
            );
        }

        const history = await response.json();

        drawOccupancyChart(history);

    } catch (error) {
        console.error(
            "Failed to load occupancy history:",
            error
        );
    }
}


function drawOccupancyChart(history) {
    const canvas = document.getElementById("occupancyChart");

    if (!canvas) {
        console.error("occupancyChart element not found.");
        return;
    }

    const container = canvas.parentElement;

    const width = container.clientWidth;
    const height = container.clientHeight;

    const dpr = window.devicePixelRatio || 1;

    canvas.width = width * dpr;
    canvas.height = height * dpr;

    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;

    const ctx = canvas.getContext("2d");

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    if (!history.length) {
        ctx.fillStyle = "#6b7280";
        ctx.font = "14px Arial";
        ctx.fillText(
            "No historical data available.",
            20,
            30
        );
        return;
    }

    // API returns newest first.
    // Reverse it for chronological order.
    const records = [...history].reverse();

    const padding = {
        top: 20,
        right: 20,
        bottom: 40,
        left: 45
    };

    const chartWidth =
        width - padding.left - padding.right;

    const chartHeight =
        height - padding.top - padding.bottom;

    const capacity = Math.max(
        ...records.map(
            record => Number(record.capacity)
        ),
        1
    );

    // Grid
    ctx.strokeStyle = "#e5e7eb";
    ctx.lineWidth = 1;

    ctx.fillStyle = "#6b7280";
    ctx.font = "11px Arial";

    for (let i = 0; i <= 4; i++) {
        const value = Math.round(
            capacity - (capacity / 4) * i
        );

        const y =
            padding.top +
            (chartHeight / 4) * i;

        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(width - padding.right, y);
        ctx.stroke();

        ctx.fillText(
            value.toString(),
            10,
            y + 4
        );
    }

    // Occupancy line
    ctx.strokeStyle = "#2563eb";
    ctx.lineWidth = 3;

    ctx.beginPath();

    records.forEach((record, index) => {
        const occupied = Number(record.occupied);

        const x =
            padding.left +
            (
                index /
                Math.max(records.length - 1, 1)
            ) *
            chartWidth;

        const y =
            padding.top +
            chartHeight -
            (
                occupied / capacity
            ) *
            chartHeight;

        if (index === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });

    ctx.stroke();

    // Data points
    ctx.fillStyle = "#2563eb";

    records.forEach((record, index) => {
        const occupied = Number(record.occupied);

        const x =
            padding.left +
            (
                index /
                Math.max(records.length - 1, 1)
            ) *
            chartWidth;

        const y =
            padding.top +
            chartHeight -
            (
                occupied / capacity
            ) *
            chartHeight;

        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fill();
    });

    // Time labels
    ctx.fillStyle = "#6b7280";
    ctx.font = "11px Arial";

    const firstTime =
        new Date(
            records[0].timestamp
        ).toLocaleTimeString();

    const lastTime =
        new Date(
            records[records.length - 1].timestamp
        ).toLocaleTimeString();

    ctx.textAlign = "left";

    ctx.fillText(
        firstTime,
        padding.left,
        height - 12
    );

    ctx.textAlign = "right";

    ctx.fillText(
        lastTime,
        width - padding.right,
        height - 12
    );

    ctx.textAlign = "left";
}


// ------------------------------------------
// Start dashboard
// ------------------------------------------

updateDashboard();
loadHistory();

setInterval(updateDashboard, 1000);
setInterval(loadHistory, 10000);