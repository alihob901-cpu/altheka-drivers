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
        try {
            const response = await fetch('/api/data', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(item)
            });
            const result = await response.json();
            if (result.isOk) this.loadData();
            return result;
        } catch(e) {
            return {isOk: false, error: e.message};
        }
    },
    
    update: async function(item) {
        try {
            const response = await fetch(`/api/data/${item.__backendId}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(item)
            });
            const result = await response.json();
            if (result.isOk) this.loadData();
            return result;
        } catch(e) {
            return {isOk: false, error: e.message};
        }
    },
    
    delete: async function(item) {
        try {
            const response = await fetch(`/api/data/${item.__backendId}`, {
                method: 'DELETE'
            });
            const result = await response.json();
            if (result.isOk) this.loadData();
            return result;
        } catch(e) {
            return {isOk: false, error: e.message};
        }
    }
};
