(function () {
    const palette = [
        '#506d4e', '#dca36a', '#9eaf83', '#d77d66', '#7895a3',
        '#b6a0c9', '#d4c56e', '#6e8d7a', '#b7a39a'
    ];

    const formatRupees = (value) =>
        '₹' + Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 });

    const readData = (id) => {
        const node = document.getElementById(id);
        if (!node) return null;
        try {
            return JSON.parse(node.textContent);
        } catch (_) {
            return null;
        }
    };

    // ------------------------------------------------------------
    // Daily spending line chart
    // ------------------------------------------------------------
    const daily = readData('daily-data');
    const dailyCanvas = document.getElementById('dailyChart');

    if (daily && dailyCanvas && window.Chart) {
        new Chart(dailyCanvas, {
            type: 'line',
            data: {
                labels: daily.labels,
                datasets: [{
                    data: daily.values,
                    borderColor: '#506d4e',
                    backgroundColor: 'rgba(80, 109, 78, .12)',
                    fill: true,
                    tension: .36,
                    pointRadius: 3,
                    pointBackgroundColor: '#506d4e',
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) => ' ' + formatRupees(context.raw)
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#8b9187', maxRotation: 0, autoSkip: true }
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: '#edf0e9' },
                        ticks: {
                            color: '#8b9187',
                            callback: (value) => '₹' + value.toLocaleString('en-IN')
                        }
                    }
                }
            }
        });
    }

    // ------------------------------------------------------------
    // Spending by category doughnut chart
    // ------------------------------------------------------------
    const category = readData('category-data');
    const categoryCanvas = document.getElementById('categoryChart');

    if (category && categoryCanvas && window.Chart) {
        new Chart(categoryCanvas, {
            type: 'doughnut',
            data: {
                labels: category.labels,
                datasets: [{
                    data: category.values,
                    backgroundColor: palette,
                    borderWidth: 0,
                    hoverOffset: 5
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '70%',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) => ' ' + context.label + ': ' + formatRupees(context.raw)
                        }
                    }
                }
            }
        });
    }

    // ------------------------------------------------------------
    // Download an HTML table as a CSV file (used on the Reports page)
    // ------------------------------------------------------------
    window.downloadTableCSV = function (tableId, filename) {
        const table = document.getElementById(tableId);
        if (!table) return;

        const rows = Array.from(table.querySelectorAll('tr')).map((row) =>
            Array.from(row.querySelectorAll('th, td'))
                .map((cell) => {
                    const text = cell.innerText
                        .replace(/"/g, '""')
                        .replace(/\s+/g, ' ')
                        .trim();
                    return '"' + text + '"';
                })
                .join(',')
        );

        // The \uFEFF marker makes Excel read the file as UTF-8
        const blob = new Blob(['\uFEFF' + rows.join('\r\n')], {
            type: 'text/csv;charset=utf-8;'
        });

        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(link.href);
    };
})();
