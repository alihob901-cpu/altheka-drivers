window.dataSdk = {
    init: function(handler) {
        this.handler = handler;
        this.loadData();
    },
    loadData: async function() {
        const response = await fetch('/api/data');
        const data = await response.json();
        if (this.handler && this.handler.onDataChanged) {
            this.handler.onDataChanged(data);
        }
    },
    create: async function(item) {
        const response = await fetch('/api/data', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(item)
        });
        return await response.json();
    },
    update: async function(item) {
        const response = await fetch(/api/data/, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(item)
        });
        return await response.json();
    },
    delete: async function(item) {
        const response = await fetch(/api/data/, {
            method: 'DELETE'
        });
        return await response.json();
    }
};
