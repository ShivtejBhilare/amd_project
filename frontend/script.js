const API_BASE = "/api";
let activeComplaintId = null;
let activeDevTicketId = null;

document.addEventListener('DOMContentLoaded', () => {
    loadDropdowns();
    pollModelStatus();

    // Elements
    const btnClient = document.getElementById('btn-client-profile');
    const btnDev = document.getElementById('btn-dev-profile');
    const clientNav = document.getElementById('client-nav');
    const devNav = document.getElementById('dev-nav');
    
    const viewCustomerSetup = document.getElementById('customer-setup-view');
    const viewCustomerChat = document.getElementById('customer-chat-view');
    const viewAgentDashboard = document.getElementById('agent-view');
    const viewCopilot = document.getElementById('copilot-view');

    // Switch to Client Profile
    btnClient.addEventListener('click', () => {
        btnClient.classList.add('active'); btnDev.classList.remove('active');
        clientNav.style.display = 'block'; devNav.style.display = 'none';
        
        switchView(viewCustomerSetup);
        document.getElementById('btn-new-ticket').classList.add('active');
        fetchMyTickets();
    });

    // Switch to Dev Profile
    btnDev.addEventListener('click', () => {
        btnDev.classList.add('active'); btnClient.classList.remove('active');
        devNav.style.display = 'block'; clientNav.style.display = 'none';
        
        switchView(viewAgentDashboard);
        document.getElementById('btn-dev-kanban').classList.add('active');
        document.getElementById('btn-dev-copilot').classList.remove('active');
        loadDashboard();
    });

    // Client Nav Buttons
    document.getElementById('btn-new-ticket').addEventListener('click', () => {
        switchView(viewCustomerSetup);
        activeComplaintId = null;
    });

    // Dev Nav Buttons
    document.getElementById('btn-dev-kanban').addEventListener('click', (e) => {
        e.target.classList.add('active'); document.getElementById('btn-dev-copilot').classList.remove('active');
        switchView(viewAgentDashboard);
        loadDashboard();
    });
    document.getElementById('btn-dev-copilot').addEventListener('click', (e) => {
        e.target.classList.add('active'); document.getElementById('btn-dev-kanban').classList.remove('active');
        switchView(viewCopilot);
    });

    // Setup New Ticket
    document.getElementById('setup-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const cid = document.getElementById('customer-select').value;
        const pid = document.getElementById('project-select').value;
        const text = document.getElementById('initial-issue').value;
        
        const fd = new FormData();
        fd.append('customer_id', cid);
        fd.append('project_id', pid);
        fd.append('text', text);

        switchView(viewCustomerChat);
        document.getElementById('chat-history').innerHTML = '';
        appendBubble('chat-history', 'user', text);
        showLoading('chat-history');
        
        try {
            const res = await fetch(`${API_BASE}/complaints`, { method: 'POST', body: fd });
            const data = await res.json();
            activeComplaintId = data.complaint_id;
            document.getElementById('active-ticket-id').textContent = `#${activeComplaintId}`;
            removeLoading('chat-history');
            appendBubble('chat-history', 'assistant', data.agent_reply);
            fetchMyTickets();
        } catch (e) {
            removeLoading('chat-history');
            appendBubble('chat-history', 'assistant', "Connection error.");
        }
    });

    // Follow-up Chat
    document.getElementById('chat-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const textInput = document.getElementById('chat-message');
        const text = textInput.value;
        textInput.value = '';
        appendBubble('chat-history', 'user', text);

        const fd = new FormData();
        fd.append('complaint_id', activeComplaintId);
        fd.append('text', text);

        showLoading('chat-history');
        try {
            const res = await fetch(`${API_BASE}/chat`, { method: 'POST', body: fd });
            const data = await res.json();
            removeLoading('chat-history');
            appendBubble('chat-history', 'assistant', data.agent_reply);
            fetchMyTickets(); // Refresh statuses
        } catch (e) {
            removeLoading('chat-history');
        }
    });

    // Global Copilot Chat
    document.getElementById('copilot-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const textInput = document.getElementById('copilot-message');
        const text = textInput.value;
        textInput.value = '';
        appendBubble('copilot-history', 'user', text);

        const fd = new FormData();
        fd.append('query', text);

        showLoading('copilot-history');
        try {
            const res = await fetch(`${API_BASE}/developer_chat`, { method: 'POST', body: fd });
            const data = await res.json();
            removeLoading('copilot-history');
            appendBubble('copilot-history', 'assistant', data.reply);
        } catch(e) { removeLoading('copilot-history'); }
    });

    // Modal Ticket Copilot Chat
    document.getElementById('modal-copilot-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const historyBox = document.getElementById('modal-copilot-history');
        historyBox.style.display = 'flex';
        
        const textInput = document.getElementById('modal-copilot-message');
        const text = textInput.value;
        textInput.value = '';
        appendBubble('modal-copilot-history', 'user', text);

        const fd = new FormData();
        fd.append('query', text);
        if (activeDevTicketId) {
            fd.append('ticket_id', activeDevTicketId);
        }

        showLoading('modal-copilot-history');
        try {
            const res = await fetch(`${API_BASE}/developer_chat`, { method: 'POST', body: fd });
            const data = await res.json();
            removeLoading('modal-copilot-history');
            appendBubble('modal-copilot-history', 'assistant', data.reply);
            
            // Refresh timeline in case Copilot updated the ETA
            openDevTimeline(activeDevTicketId, document.getElementById('modal-ticket-title').textContent.split(' - ')[1]);
        } catch(e) { removeLoading('modal-copilot-history'); }
    });

    // Dashboard
    document.getElementById('refresh-dashboard').addEventListener('click', loadDashboard);
    document.getElementById('employee-select').addEventListener('change', loadDashboard);

    // Modal
    document.querySelector('.close-modal').addEventListener('click', () => {
        document.getElementById('timeline-modal').style.display = 'none';
    });
    
    // Listen for customer change to refresh tickets
    document.getElementById('customer-select').addEventListener('change', fetchMyTickets);
});

function switchView(viewElem) {
    document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
    viewElem.classList.add('active');
}

async function loadDropdowns() {
    const custRes = await fetch(`${API_BASE}/customers`);
    const custData = await custRes.json();
    const custSel = document.getElementById('customer-select');
    custData.forEach(c => custSel.add(new Option(c.name, c.id)));
    fetchMyTickets(); // initial load

    const projRes = await fetch(`${API_BASE}/projects`);
    const projData = await projRes.json();
    const projSel = document.getElementById('project-select');
    projData.forEach(p => projSel.add(new Option(p.name, p.id)));

    const empRes = await fetch(`${API_BASE}/employees`);
    const empData = await empRes.json();
    const empSel = document.getElementById('employee-select');
    empSel.add(new Option('All Engineers', 'all'));
    empData.forEach(e => empSel.add(new Option(`${e.name} (${e.specialty})`, e.name)));
}

function appendBubble(containerId, role, text) {
    const box = document.getElementById(containerId);
    const div = document.createElement('div');
    div.className = `chat-bubble chat-${role}`;
    
    if (role === 'assistant') {
        div.innerHTML = marked.parse(text);
    } else {
        div.innerHTML = text.replace(/\n/g, '<br>');
    }
    
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
}

function showLoading(containerId) {
    const box = document.getElementById(containerId);
    const div = document.createElement('div');
    div.className = 'chat-bubble chat-assistant loading-bubble';
    div.innerHTML = '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';
    div.id = `loading-${containerId}`;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
}

function removeLoading(containerId) {
    const loader = document.getElementById(`loading-${containerId}`);
    if (loader) loader.remove();
}

let previousModelStatus = "UNINITIALIZED";

async function pollModelStatus() {
    try {
        const res = await fetch(`${API_BASE}/status`);
        const data = await res.json();
        const banner = document.getElementById('model-status-banner');
        
        if (data.model_status === "READY" && previousModelStatus === "LOADING") {
            showToast("✅ Backend LLM Loaded Successfully!", "success");
        }
        
        if (data.model_status === "LOADING" || data.model_status === "UNINITIALIZED") {
            banner.style.display = "flex";
            setTimeout(pollModelStatus, 3000);
        } else {
            banner.style.display = "none";
        }
        previousModelStatus = data.model_status;
    } catch (e) {
        setTimeout(pollModelStatus, 3000);
    }
}

function showToast(message, type) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerText = message;
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 500);
    }, 3000);
}

async function fetchMyTickets() {
    const cid = document.getElementById('customer-select').value;
    if (!cid) return;
    
    const res = await fetch(`${API_BASE}/customer/tickets/${cid}`);
    const tickets = await res.json();
    
    const list = document.getElementById('my-tickets-list');
    list.innerHTML = '';
    
    tickets.forEach(t => {
        const div = document.createElement('div');
        div.className = 'sidebar-ticket';
        div.innerHTML = `<strong>#${t.id} - ${t.project_name}</strong><br>Status: ${t.status}`;
        div.onclick = () => openCustomerTicket(t.id);
        list.appendChild(div);
    });
}

async function openCustomerTicket(ticketId) {
    activeComplaintId = ticketId;
    document.getElementById('active-ticket-id').textContent = `#${ticketId}`;
    switchView(document.getElementById('customer-chat-view'));
    
    const box = document.getElementById('chat-history');
    box.innerHTML = 'Loading...';
    
    const res = await fetch(`${API_BASE}/tickets/${ticketId}/timeline`);
    const data = await res.json();
    box.innerHTML = '';
    
    data.forEach(msg => appendBubble('chat-history', msg.role, msg.content));
}

function loadDashboard() {
    const grid = document.getElementById('dashboard-grid');
    const empFilter = document.getElementById('employee-select').value;
    grid.innerHTML = '<p>Loading...</p>';
    
    fetch(`${API_BASE}/dashboard/complaints`)
        .then(res => res.json())
        .then(data => {
            grid.innerHTML = '';
            const filtered = data.filter(t => empFilter === 'all' || t.assigned_employee === empFilter);
            
            if (filtered.length === 0) {
                grid.innerHTML = '<p style="color: var(--text-muted)">No tickets match this view.</p>';
                return;
            }
            
            filtered.forEach(ticket => {
                const priorityClass = `priority-${ticket.priority ? ticket.priority.toLowerCase() : 'low'}`;
                const card = document.createElement('div');
                card.className = 'ticket-card';
                card.onclick = () => openDevTimeline(ticket.id, ticket.project_name);
                
                let badge = ticket.status === 'RESOLVED' ? `<span class="priority-badge priority-low">RESOLVED</span>` : `<span class="priority-badge ${priorityClass}">${ticket.priority}</span>`;
                
                card.innerHTML = `
                    <div class="ticket-header">
                        ${badge}
                        <span class="team-badge">${ticket.assigned_employee || 'Unassigned'}</span>
                    </div>
                    <div style="margin-bottom: 8px; font-size: 0.8rem; color: var(--text-muted);">
                        Ticket #${ticket.id} | ${ticket.project_name}
                    </div>
                    <div style="margin-bottom: 8px; font-size: 0.8rem; color: var(--priority-medium);">
                        ETA: ${ticket.eta || 'N/A'}
                    </div>
                    <div class="ticket-content">${ticket.text}</div>
                `;
                grid.appendChild(card);
            });
        });
}

async function openDevTimeline(ticketId, projectName) {
    activeDevTicketId = ticketId;
    const modal = document.getElementById('timeline-modal');
    const timelineBox = document.getElementById('modal-timeline');
    document.getElementById('modal-ticket-title').textContent = `Ticket #${ticketId} Timeline - ${projectName}`;
    
    document.getElementById('modal-copilot-history').innerHTML = '';
    document.getElementById('modal-copilot-history').style.display = 'none';
    
    timelineBox.innerHTML = 'Loading...';
    modal.style.display = 'block';

    try {
        const res = await fetch(`${API_BASE}/tickets/${ticketId}/timeline`);
        const data = await res.json();
        timelineBox.innerHTML = '';
        data.forEach(msg => {
            const div = document.createElement('div');
            div.className = `chat-bubble chat-${msg.role}`;
            div.innerHTML = `<strong>${msg.role === 'user' ? 'Customer' : 'Agent'}</strong><br>${msg.content.replace(/\n/g, '<br>')}`;
            timelineBox.appendChild(div);
        });
        timelineBox.scrollTop = timelineBox.scrollHeight;
    } catch (e) {
        timelineBox.innerHTML = 'Failed to load timeline.';
    }
}
