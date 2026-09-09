async function updateStatus() {

    try {

        const response = await fetch(
            "/status"
        );

        const data = await response.json();

        document.getElementById(
            "capacity"
        ).textContent = data.capacity;

        document.getElementById(
            "occupied"
        ).textContent = data.occupied;

        document.getElementById(
            "available"
        ).textContent = data.available;

        const grid =
            document.getElementById(
                "parking-grid"
            );

        grid.innerHTML = "";

        for (
            const [name, occupied]
            of Object.entries(data.spaces)
        ) {

            const space =
                document.createElement(
                    "div"
                );

            space.className =
                `space ${
                    occupied
                        ? "occupied"
                        : "available"
                }`;

            space.innerHTML = `
                <div class="space-name">
                    ${name}
                </div>

                <div class="space-status">
                    ${
                        occupied
                            ? "OCCUPIED"
                            : "AVAILABLE"
                    }
                </div>
            `;

            grid.appendChild(space);
        }

        document.getElementById(
            "updated"
        ).textContent =
            `Updated ${new Date()
                .toLocaleTimeString()}`;

    } catch (error) {

        document.getElementById(
            "updated"
        ).textContent =
            "Connection unavailable";
    }
}


// Update immediately.
updateStatus();


// Refresh every second.
setInterval(
    updateStatus,
    1000
);