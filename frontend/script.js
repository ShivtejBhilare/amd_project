const API_BASE = "http://localhost:8001/api";
let activeComplaintId = null;

document.addEventListener('DOMContentLoaded', () => {
    // Load dropdowns
    loadDropdowns();

    // Profile Switcher
    const btnClient = document.getElementById('btn-client-profile');
    const btnDev = document.getElementById('btn-dev-profile');
    const clientNav = document.getElementById('client-nav');
    const devNav = document.getElementById('dev-nav');
    const customerView = document.getElementById('customer-view');
    const agentView = document.getElementById('agent-view');

    btnClient.addEventListener('click', () => {
        btnClient.classList.add('active'); btnDev.classList.remove('active');
        clientNav.style.display = 'block'; devNav.style.display = 'none';
        customerView.classList.add('active'); agentView.classList.remove('active');
    });

    btnDev.addEventListener('click', () => {
        btnDev.classList.add('active'); btnClient.classList.remove('active');
        devNav.style.display = 'block'; clientNav.style.display = 'none';
        agentView.classList.add('active'); customerView.classList.remove('active');
        loadDashboard();
    });

    // Start Session (Client)
    document.getElementById('setup-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const cid = document.getElementById('customer-select').value;
        const pid = document.getElementById('project-select').value;
        const text = document.getElementById('initial-issue').value;
        
        const fd = new FormData();
        fd.append('customer_id', cid);
        fd.append('project_id', pid);
        fd.append('text', text);

        appendBubble('user', text);
        document.getElementById('ticket-setup').style.display = 'none';
        document.getElementById('chat-interface').style.display = 'flex';

        try {
            const res = await fetch(`${API_BASE}/complaints`, { method: 'POST', body: fd });
            const data = await res.json();
            activeComplaintId = data.complaint_id;
            appendBubble('assistant', data.agent_result.agent_reply);
        } catch (err) {
            appendBubble('assistant', 'Error connecting to backend.');
        }
    });

    // Follow-up Chat (Client)
    document.getElementById('chat-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const textInput = document.getElementById('chat-message');
        const text = textInput.value;
        textInput.value = '';
        appendBubble('user', text);

        const fd = new FormData();
        fd.append('complaint_id', activeComplaintId);
        fd.append('text', text);

        try {
            const res = await fetch(`${API_BASE}/chat`, { method: 'POST', body: fd });
            const data = await res.json();
            appendBubble('assistant', data.agent_reply);
        } catch (err) {
            appendBubble('assistant', 'Network Error.');
        }
    });

    // Dashboard (Dev)
    document.getElementById('refresh-dashboard').addEventListener('click', loadDashboard);
    document.getElementById('employee-select').addEventListener('change', loadDashboard);

    // Modal close
    document.querySelector('.close-modal').addEventListener('click', () => {
        document.getElementById('timeline-modal').style.display = 'none';
    });
});

async function loadDropdowns() {
    const custRes = await fetch(`${API_BASE}/customers`);
    const custData = await custRes.json();
    const custSel = document.getElementById('customer-select');
    custData.forEach(c => custSel.add(new Option(c.name, c.id)));

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

function appendBubble(role, text) {
    const box = document.getElementById('chat-history');
    const div = document.createElement('div');
    div.className = `chat-bubble chat-${role}`;
    div.innerHTML = text.replace(/\n/g, '<br>');
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
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
                card.onclick = () => openTimeline(ticket.id, ticket.project_name);
                
                let badge = ticket.status === 'RESOLVED' ? `<span class="priority-badge priority-low">RESOLVED</span>` : `<span class="priority-badge ${priorityClass}">${ticket.priority}</span>`;
                
                card.innerHTML = `
                    <div class="ticket-header">
                        ${badge}
                        <span class="team-badge">${ticket.assigned_employee || 'Unassigned'}</span>
                    </div>
                    <div style="margin-bottom: 8px; font-size: 0.8rem; color: var(--text-muted);">
                        Ticket #${ticket.id} | Project: ${ticket.project_name}
                    </div>
                    <div class="ticket-content">${ticket.text}</div>
                `;
                grid.appendChild(card);
            });
        });
}

async function openTimeline(ticketId, projectName) {
    const modal = document.getElementById('timeline-modal');
    const timelineBox = document.getElementById('modal-timeline');
    document.getElementById('modal-ticket-title').textContent = `Ticket #${ticketId} Timeline - ${projectName}`;
    
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
