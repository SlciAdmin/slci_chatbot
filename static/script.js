// Global variables
let currentDownloadData = {
    state: null,
    actType: null
};

// Initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    initializeChat();
    initializeModal();
    initializeFormValidation();
    initializeRatingStars();
    initializeServiceModal();  // This now includes auto-fill
    initializeFeeModal();
});

function initializeChat() {
    const input = document.getElementById("user-input");
    if (input) input.focus();
    checkOllamaStatus();
    setInterval(checkOllamaStatus, 30000);
}

function initializeModal() {
    const modal = document.getElementById('downloadModal');
    const closeBtn = document.querySelector('.close-modal');
    const cancelBtn = document.querySelector('.modal-cancel-btn');
    if (closeBtn) closeBtn.onclick = () => closeModal();
    if (cancelBtn) cancelBtn.onclick = () => closeModal();
    window.onclick = (event) => {
        if (event.target == modal) closeModal();
    };
    const form = document.getElementById('downloadForm');
    if (form) form.addEventListener('submit', handleFormSubmit);
}  

// ============================================================================
// ENHANCED SERVICE MODAL INITIALIZATION WITH AUTO-FILL
// ============================================================================
function initializeServiceModal() {
    const serviceModal = document.getElementById('serviceModal');
    const closeServiceBtn = document.querySelector('.close-service-modal');
    
    if (closeServiceBtn) {
        closeServiceBtn.onclick = () => closeServiceModal();
    }
    
    const serviceCancelBtn = serviceModal?.querySelector('.modal-cancel-btn');
    if (serviceCancelBtn) {
        serviceCancelBtn.onclick = () => closeServiceModal();
    }
    
    const serviceForm = document.getElementById('serviceForm');
    if (serviceForm) {
        serviceForm.addEventListener('submit', handleServiceSubmit);
    }
    
    // Auto-fill form when modal opens using MutationObserver
    const modal = document.getElementById('serviceModal');
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.type === 'attributes' && mutation.attributeName === 'style') {
                if (modal.style.display === 'block') {
                    autoFillServiceForm();
                }
            }
        });
    });
    
    observer.observe(modal, { attributes: true });
    
    window.addEventListener('click', (event) => {
        if (event.target == serviceModal) closeServiceModal();
    });
    
    // Add validation listeners
    const serviceInputs = document.querySelectorAll('#serviceForm input, #serviceForm textarea');
    serviceInputs.forEach(input => {
        input.addEventListener('input', function() { validateServiceField(this); });
        input.addEventListener('blur', function() { validateServiceField(this); });
    });
}

// ============================================================================
// FEE ENQUIRY MODAL INITIALIZATION
// ============================================================================
function initializeFeeModal() {
    const feeModal = document.getElementById('feeModal');
    const closeFeeBtn = document.querySelector('.close-fee-modal');
    if (closeFeeBtn) closeFeeBtn.onclick = () => closeFeeModal();
    const feeCancelBtn = feeModal?.querySelector('.fee-cancel-btn');
    if (feeCancelBtn) feeCancelBtn.onclick = () => closeFeeModal();
    const feeForm = document.getElementById('feeForm');
    if (feeForm) feeForm.addEventListener('submit', handleFeeSubmit);
    window.addEventListener('click', (event) => {
        if (event.target == feeModal) closeFeeModal();
    });
    const feeInputs = document.querySelectorAll('#feeForm input, #feeForm textarea');
    feeInputs.forEach(input => {
        input.addEventListener('input', function() { validateFeeField(this); });
        input.addEventListener('blur', function() { validateFeeField(this); });
    });
}

function initializeRatingStars() {
    const stars = document.querySelectorAll('.rating-stars i');
    const ratingInput = document.getElementById('rating');
    if (!stars.length || !ratingInput) return;
    stars.forEach(star => {
        star.addEventListener('mouseover', function() {
            highlightStars(this.dataset.rating);
        });
        star.addEventListener('mouseout', function() {
            const currentRating = ratingInput.value;
            if (currentRating) highlightStars(currentRating);
            else resetStars();
        });
        star.addEventListener('click', function() {
            const rating = this.dataset.rating;
            ratingInput.value = rating;
            highlightStars(rating);
            this.classList.add('star-pulse');
            setTimeout(() => this.classList.remove('star-pulse'), 300);
        });
    });
}

function highlightStars(rating) {
    const stars = document.querySelectorAll('.rating-stars i');
    stars.forEach((star, index) => {
        star.className = index < rating ? 'fas fa-star' : 'far fa-star';
    });
}

function resetStars() {
    document.querySelectorAll('.rating-stars i').forEach(star => {
        star.className = 'far fa-star';
    });
}

function initializeFormValidation() {
    const form = document.getElementById('downloadForm');
    if (!form) return;
    form.querySelectorAll('input, select').forEach(input => {
        input.addEventListener('input', function() { validateField(this); });
        input.addEventListener('blur', function() { validateField(this); });
    });
}

function validateField(field) {
    if (!field) return true;
    const value = field.value.trim();
    let isValid = true, errorMessage = '';
    
    field.parentElement.querySelectorAll('.validation-icon, .error-tooltip').forEach(el => el.remove());
    
    switch(field.id) {
        case 'fullName':
            if (!value) { isValid = false; errorMessage = 'Full name is required'; }
            else if (value.length < 2) { isValid = false; errorMessage = 'Name must be at least 2 characters'; }
            break;
        case 'companyName':
            if (!value) { isValid = false; errorMessage = 'Company name is required'; }
            break;
        case 'email':
            const emailPattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
            if (!value) { isValid = false; errorMessage = 'Email is required'; }
            else if (!emailPattern.test(value)) { isValid = false; errorMessage = 'Invalid email format'; }
            break;
        case 'contactNumber':
            const phonePattern = /^[6-9]\d{9}$/;
            const cleanPhone = value.replace(/[\s\-\(\)\+]/g, '');
            if (!value) { isValid = false; errorMessage = 'Contact number is required'; }
            else if (!phonePattern.test(cleanPhone)) { isValid = false; errorMessage = 'Enter valid 10-digit mobile number'; }
            break;
        case 'designation':
            if (!value) { isValid = false; errorMessage = 'Please select your designation'; }
            break;
    }
    
    if (value && isValid) {
        const icon = document.createElement('i');
        icon.className = 'fas fa-check-circle validation-icon valid';
        field.parentElement.appendChild(icon);
        field.classList.remove('error');
    } else if (value && !isValid) {
        const icon = document.createElement('i');
        icon.className = 'fas fa-exclamation-circle validation-icon invalid';
        field.parentElement.appendChild(icon);
        field.classList.add('error');
        showFieldError(field, errorMessage);
    } else {
        field.classList.remove('error');
    }
    return isValid;
}

function validateServiceField(field) {
    if (!field) return true;
    const value = field.value.trim();
    let isValid = true, errorMessage = '';
    
    field.parentElement.querySelectorAll('.validation-icon, .error-tooltip').forEach(el => el.remove());
    
    switch(field.id) {
        case 'serviceFullName':
            if (!value) { isValid = false; errorMessage = 'Full name is required'; }
            else if (value.length < 2) { isValid = false; errorMessage = 'Name must be at least 2 characters'; }
            break;
        case 'serviceCompanyName':
            if (!value) { isValid = false; errorMessage = 'Company name is required'; }
            break;
        case 'serviceEmail':
            const emailPattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
            if (!value) { isValid = false; errorMessage = 'Email is required'; }
            else if (!emailPattern.test(value)) { isValid = false; errorMessage = 'Invalid email format'; }
            break;
        case 'serviceContactNumber':
            const phonePattern = /^[6-9]\d{9}$/;
            const cleanPhone = value.replace(/[\s\-\(\)\+]/g, '');
            if (!value) { isValid = false; errorMessage = 'Contact number is required'; }
            else if (!phonePattern.test(cleanPhone)) { isValid = false; errorMessage = 'Enter valid 10-digit mobile number'; }
            break;
        case 'serviceQuery':
            if (!value) { isValid = false; errorMessage = 'Please enter your query'; }
            else if (value.length < 10) { isValid = false; errorMessage = 'Query must be at least 10 characters'; }
            break;
    }
    
    if (value && isValid) {
        const icon = document.createElement('i');
        icon.className = 'fas fa-check-circle validation-icon valid';
        field.parentElement.appendChild(icon);
        field.classList.remove('error');
    } else if (value && !isValid) {
        const icon = document.createElement('i');
        icon.className = 'fas fa-exclamation-circle validation-icon invalid';
        field.parentElement.appendChild(icon);
        field.classList.add('error');
        showFieldError(field, errorMessage);
    } else {
        field.classList.remove('error');
    }
    return isValid;
}

// ============================================================================
// FEE FIELD VALIDATION
// ============================================================================
function validateFeeField(field) {
    if (!field) return true;
    const value = field.value.trim();
    let isValid = true, errorMessage = '';
    
    field.parentElement.querySelectorAll('.validation-icon, .error-tooltip').forEach(el => el.remove());
    
    switch(field.id) {
        case 'feeFullName':
            if (!value) { isValid = false; errorMessage = 'Full name is required'; }
            else if (value.length < 2) { isValid = false; errorMessage = 'Name must be at least 2 characters'; }
            break;
        case 'feeCompanyName':
            if (!value) { isValid = false; errorMessage = 'Company name is required'; }
            break;
        case 'feeEmail':
            const emailPattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
            if (!value) { isValid = false; errorMessage = 'Email is required'; }
            else if (!emailPattern.test(value)) { isValid = false; errorMessage = 'Invalid email format'; }
            break;
        case 'feeContactNumber':
            const phonePattern = /^[6-9]\d{9}$/;
            const cleanPhone = value.replace(/[\s\-\(\)\+]/g, '');
            if (!value) { isValid = false; errorMessage = 'Contact number is required'; }
            else if (!phonePattern.test(cleanPhone)) { isValid = false; errorMessage = 'Enter valid 10-digit mobile number'; }
            break;
        case 'feeDescription':
            if (!value) { isValid = false; errorMessage = 'Please describe your requirements'; }
            else if (value.length < 20) { isValid = false; errorMessage = 'Description must be at least 20 characters'; }
            break;
    }
    
    if (value && isValid) {
        const icon = document.createElement('i');
        icon.className = 'fas fa-check-circle validation-icon valid';
        field.parentElement.appendChild(icon);
        field.classList.remove('error');
    } else if (value && !isValid) {
        const icon = document.createElement('i');
        icon.className = 'fas fa-exclamation-circle validation-icon invalid';
        field.parentElement.appendChild(icon);
        field.classList.add('error');
        showFieldError(field, errorMessage);
    } else {
        field.classList.remove('error');
    }
    return isValid;
}

function validateFeeForm() {
    const form = document.getElementById('feeForm');
    if (!form) return false;
    let isValid = true;
    form.querySelectorAll('input, textarea').forEach(input => {
        if (!validateFeeField(input)) isValid = false;
    });
    return isValid;
}

function showFieldError(field, message) {
    const tooltip = document.createElement('div');
    tooltip.className = 'error-tooltip';
    tooltip.innerHTML = `<span class="tooltip-text">${message}</span>`;
    field.parentElement.appendChild(tooltip);
    setTimeout(() => tooltip.remove(), 3000);
}

function validateForm() {
    const form = document.getElementById('downloadForm');
    if (!form) return false;
    let isValid = true;
    form.querySelectorAll('input, select').forEach(input => {
        if (!validateField(input)) isValid = false;
    });
    const rating = document.getElementById('rating').value;
    if (!rating) {
        showNotification('Please rate our service', 'error');
        isValid = false;
    }
    return isValid;
}

function validateServiceForm() {
    const form = document.getElementById('serviceForm');
    if (!form) return false;
    let isValid = true;
    form.querySelectorAll('input, textarea').forEach(input => {
        if (!validateServiceField(input)) isValid = false;
    });
    return isValid;
}

function openDownloadModal(state, actType) {
    currentDownloadData = { state, actType };
    document.getElementById('modalState').value = state;
    document.getElementById('modalActType').value = actType;
    const form = document.getElementById('downloadForm');
    if (form) {
        form.reset();
        form.querySelectorAll('.validation-icon, .error-tooltip').forEach(el => el.remove());
        form.querySelectorAll('input, select').forEach(input => input.classList.remove('error'));
    }
    resetStars();
    const modal = document.getElementById('downloadModal');
    if (modal) {
        modal.style.display = 'block';
        document.body.style.overflow = 'hidden';
        setTimeout(() => document.getElementById('fullName')?.focus(), 100);
    }
}

// ============================================================================
// ENHANCED OPEN SERVICE MODAL WITH AUTO-FILL
// ============================================================================
function openServiceModal(serviceName) {
    console.log("Opening service modal for:", serviceName); // Debug log
    
    const modal = document.getElementById('serviceModal');
    const selectedServiceInput = document.getElementById('selectedService');
    
    if (!modal || !selectedServiceInput) {
        console.error("Modal elements not found!");
        return;
    }
    
    // Set the service name
    selectedServiceInput.value = serviceName;
    
    // Reset and clear form
    const form = document.getElementById('serviceForm');
    if (form) {
        form.reset();
        // Clear all validation icons and error classes
        form.querySelectorAll('.validation-icon, .error-tooltip').forEach(el => el.remove());
        form.querySelectorAll('input, textarea').forEach(input => {
            input.classList.remove('error');
        });
    }
    
    // Auto-fill with saved data
    autoFillServiceForm();
    
    // Show modal
    modal.style.display = 'block';
    document.body.style.overflow = 'hidden';
    
    // Focus on first field
    setTimeout(() => {
        const firstField = document.getElementById('serviceFullName');
        if (firstField) firstField.focus();
    }, 100);
}

// ============================================================================
// FEE MODAL OPEN/CLOSE
// ============================================================================
function openFeeModal() {
    const form = document.getElementById('feeForm');
    if (form) {
        form.reset();
        form.querySelectorAll('.validation-icon, .error-tooltip').forEach(el => el.remove());
        form.querySelectorAll('input, textarea').forEach(input => input.classList.remove('error'));
    }
    const modal = document.getElementById('feeModal');
    modal.style.display = 'block';
    document.body.style.overflow = 'hidden';
    setTimeout(() => document.getElementById('feeFullName')?.focus(), 100);
}

function closeModal() {
    const modal = document.getElementById('downloadModal');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = 'auto';
    }
}

function closeServiceModal() {
    const modal = document.getElementById('serviceModal');
    modal.style.display = 'none';
    document.body.style.overflow = 'auto';
}

function closeFeeModal() {
    const modal = document.getElementById('feeModal');
    modal.style.display = 'none';
    document.body.style.overflow = 'auto';
}

// ✅ FIXED: Two-step PDF download flow
async function handleFormSubmit(event) {
    event.preventDefault();
    if (!validateForm()) return;
    
    showLoadingOverlay();
    
    const formData = {
        fullName: document.getElementById('fullName').value.trim(),
        companyName: document.getElementById('companyName').value.trim(),
        email: document.getElementById('email').value.trim(),
        contactNumber: document.getElementById('contactNumber').value.trim(),
        designation: document.getElementById('designation').value,
        rating: document.getElementById('rating').value,
        state: currentDownloadData.state,
        actType: currentDownloadData.actType
    };
    
    try {
        const response = await fetch('/request-download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });
        const data = await response.json();
        
        if (data.success && data.downloadToken) {
            closeModal();
            const downloadRecord = {
                downloadId: data.downloadId,
                state: currentDownloadData.state,
                actType: currentDownloadData.actType,
                timestamp: new Date().toISOString(),
                token: data.downloadToken
            };
            localStorage.setItem('lastDownload', JSON.stringify(downloadRecord));
            showSuccessMessage(data.downloadId);
            setTimeout(() => {
                window.location.href = `/generate-pdf/${data.downloadToken}`;
            }, 800);
        } else {
            throw new Error(data.error || 'Form submission failed');
        }
    } catch (error) {
        console.error('Form submission error:', error);
        showNotification(error.message || 'Failed to process request', 'error');
    } finally {
        hideLoadingOverlay();
    }
}

// ============================================================================
// ENHANCED SERVICE ENQUIRY HANDLER WITH AUTO-SAVE
// ============================================================================
async function handleServiceSubmit(event) {
    event.preventDefault();
    if (!validateServiceForm()) return;
    
    const formData = {
        fullName: document.getElementById('serviceFullName').value.trim(),
        companyName: document.getElementById('serviceCompanyName').value.trim(),
        email: document.getElementById('serviceEmail').value.trim(),
        contactNumber: document.getElementById('serviceContactNumber').value.trim(),
        service: document.getElementById('selectedService').value,
        query: document.getElementById('serviceQuery').value.trim()
    };
    
    console.log("Submitting service enquiry:", formData); // Debug log
    
    try {
        showLoadingOverlay();
        const response = await fetch('/submit-service-enquiry', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });
        
        const data = await response.json();
        console.log("Service submission response:", data); // Debug log
        
        if (data.success) {
            closeServiceModal();
            
            // Show success message in chat
            const successMessage = `
            <div style="text-align: center; padding: 15px; background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%); border-radius: 10px; border-left: 4px solid #28a745;">
                <i class="fas fa-check-circle" style="color: #28a745; font-size: 24px;"></i>
                <div style="margin-top: 10px;">
                    <strong style="font-size: 16px; color: #155724;">✅ Enquiry Submitted Successfully!</strong>
                    <p style="margin: 10px 0; color: #155724;">Thank you for your interest in: <strong>${formData.service}</strong></p>
                    <p style="margin: 5px 0; color: #155724;">Reference ID: <strong>${data.enquiryId || 'N/A'}</strong></p>
                    <p style="margin: 5px 0; color: #155724;">Our team will contact you within 24 hours.</p>
                </div>
            </div>
            `;
            addMessage(successMessage, 'bot');
            
            // Also show a notification
            showNotification('Enquiry submitted successfully! Check your email for confirmation.', 'success');
            
            // Save user data for auto-fill in future submissions
            localStorage.setItem('userEmail', formData.email);
            localStorage.setItem('userName', formData.fullName);
            localStorage.setItem('userCompany', formData.companyName);
            localStorage.setItem('userPhone', formData.contactNumber);
        } else {
            throw new Error(data.error || "Submission failed");
        }
    } catch (error) {
        console.error('Service form error:', error);
        showNotification(error.message || "Failed to submit enquiry. Please try again.", "error");
    } finally {
        hideLoadingOverlay();
    }
}

// ============================================================================
// FEE ENQUIRY SUBMIT HANDLER
// ============================================================================
async function handleFeeSubmit(event) {
    event.preventDefault();
    if (!validateFeeForm()) return;
    
    showLoadingOverlay();
    
    const formData = {
        fullName: document.getElementById('feeFullName').value.trim(),
        companyName: document.getElementById('feeCompanyName').value.trim(),
        email: document.getElementById('feeEmail').value.trim(),
        contactNumber: document.getElementById('feeContactNumber').value.trim(),
        description: document.getElementById('feeDescription').value.trim()
    };
    
    try {
        const response = await fetch('/submit-fee-enquiry', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });
        const data = await response.json();
        
        if (data.success) {
            closeFeeModal();
            addMessage(`
            <div class="success-message-content">
            <i class="fas fa-check-circle" style="color: #28a745; font-size: 24px;"></i>
            <strong style="font-size: 16px;">✅ Fee Enquiry Submitted Successfully!</strong><br>
            <p style="margin: 10px 0; color: #666;">Thank you for submitting your enquiry.</p>
            <p style="margin: 5px 0; color: #666;">📧 Our pricing team will contact you within 24 hours.</p>
            <p style="margin: 8px 0; color: #1a237e; font-weight: bold;">Support Email: slciaiagent@gmail.com</p>
            </div>
            `, 'bot');
            showNotification('Fee enquiry submitted successfully!', 'success');
        } else {
            throw new Error(data.error || "Submission failed");
        }
    } catch (error) {
        console.error('Fee form error:', error);
        showNotification(error.message, "error");
    } finally {
        hideLoadingOverlay();
    }
}

// ============================================================================
// AUTO-FILL HELPER FUNCTION
// ============================================================================
function autoFillServiceForm() {
    const email = localStorage.getItem('userEmail');
    const name = localStorage.getItem('userName');
    const company = localStorage.getItem('userCompany');
    const phone = localStorage.getItem('userPhone');
    
    if (email) document.getElementById('serviceEmail').value = email;
    if (name) document.getElementById('serviceFullName').value = name;
    if (company) document.getElementById('serviceCompanyName').value = company;
    if (phone) document.getElementById('serviceContactNumber').value = phone;
}

function showSuccessMessage(downloadId) {
    document.querySelectorAll('.success-message').forEach(msg => msg.remove());
    const successDiv = document.createElement('div');
    successDiv.className = 'success-message';
    successDiv.innerHTML = `
    <i class="fas fa-check-circle"></i>
    <div>
    <strong>✅ Your PDF is Ready!</strong>
    </div>
    `;
    document.body.appendChild(successDiv);
    
    const chatBox = document.getElementById('chat-box');
    if (chatBox) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'bot-message';
        messageDiv.innerHTML = `
        <div class="message-content">
        <i class="fas fa-check-circle" style="color: #28a745;"></i>
        <strong>✅ Your PDF is Downloaded!</strong><br>
        Thank you for your request! Your download has been initiated.<br>
        Reference ID: #${downloadId || 'N/A'}
        </div>
        <span class="time">${getCurrentTime()}</span>
        `;
        chatBox.appendChild(messageDiv);
        chatBox.scrollTop = chatBox.scrollHeight;
    }
    setTimeout(() => successDiv.remove(), 5000);
}

function showLoadingOverlay() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) overlay.style.display = 'flex';
}

function hideLoadingOverlay() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) overlay.style.display = 'none';
}

// ============================================================================
// ENHANCED SEND MESSAGE WITH SERVICE RESPONSE HANDLING
// ============================================================================
function sendMessage() {
    const input = document.getElementById("user-input");
    if (!input) return;
    const message = input.value.trim();
    if (!message) return;
    
    const sendBtn = document.getElementById("send-btn");
    if (sendBtn) {
        sendBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        sendBtn.disabled = true;
    }
    input.disabled = true;
    
    addMessage(message, 'user');
    input.value = "";
    showTypingIndicator();
    
    fetch("/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({message: message})
    })
    .then(res => res.json())
    .then(data => {
        removeTypingIndicator();
        
        // Handle service enquiry response
        if (data.show_services) {
            addMessage(data.response, 'bot');
            return;
        }
        
        // Handle fees / pricing - Auto-open modal
        if (data.show_fee_button) {
            addMessage(data.response, 'bot');
            setTimeout(() => { openFeeModal(); }, 400);
            return;
        }
        
        // Normal bot response flow
        addMessage(data.response, 'bot');
        
        // Extract state/actType from response
        if (data.response) {
            const responseLower = data.response.toLowerCase();
            
            let actType = null;
            if (responseLower.includes('minimum wages')) actType = 'minimum_wages';
            else if (responseLower.includes('holiday list')) actType = 'holiday_list';
            else if (responseLower.includes('working hours')) actType = 'working_hours';
            else if (responseLower.includes('shop and establishment') || responseLower.includes('shop & establishment')) actType = 'shop_establishment';
            
            if (actType) {
                let state = null;
                const pattern1 = new RegExp(`(?:Minimum Wages|Holiday List|Working Hours|Shop and Establishment Act|Shop & Establishment Act)\\s*[–\\-]\\s*([A-Za-z\\s]+?)(?:<|\\n|$)`, 'i');
                const match1 = data.response.match(pattern1);
                if (match1 && match1[1]) {
                    state = match1[1].trim().replace(/[^a-zA-Z\s]/g, '').trim();
                }
                if (!state && data.state) {
                    state = data.state;
                }
                if (!state) {
                    const titleMatch = data.response.match(/<h3[^>]*>(?:Minimum Wages|Holiday List|Working Hours|Shop and Establishment Act)\\s*[–\\-]\\s*([^<]+)<\/h3>/i);
                    if (titleMatch && titleMatch[1]) {
                        state = titleMatch[1].trim();
                    }
                }
                if (state) {
                    state = state.replace(/[^a-zA-Z\s]/g, '').trim();
                    if (state.length > 1) {
                        currentDownloadData = { state: state.toLowerCase(), actType: actType };
                        console.log(`✅ Detected: ${actType} for state: ${state}`);
                    }
                }
            }
        }
    })
    .catch(error => {
        removeTypingIndicator();
        addMessage("Connection error. Please try again.", 'bot');
        console.error('Error:', error);
    })
    .finally(() => {
        if (sendBtn) {
            sendBtn.innerHTML = '<i class="fas fa-paper-plane"></i>';
            sendBtn.disabled = false;
        }
        input.disabled = false;
        input.focus();
    });
}

function addServiceEnquiryButton() {
    const chatBox = document.getElementById('chat-box');
    if (!chatBox || document.querySelector('.service-enquiry-btn')) return;
    const buttonDiv = document.createElement('div');
    buttonDiv.className = 'bot-message';
    buttonDiv.innerHTML = `
    <div class="message-content">
    <p>Would you like to know more about our compliance services?</p>
    <button onclick="openServiceModal('General Enquiry')" class="service-enquiry-btn">
    <i class="fas fa-briefcase"></i> Enquire About Services
    </button>
    </div>
    <span class="time">${getCurrentTime()}</span>
    `;
    chatBox.appendChild(buttonDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

// ============================================================================
// FEE ENQUIRY BUTTON
// ============================================================================
function addFeeEnquiryButton() {
    const chatBox = document.getElementById('chat-box');
    if (!chatBox || document.querySelector('.fee-enquiry-btn')) return;
    const buttonDiv = document.createElement('div');
    buttonDiv.className = 'bot-message';
    buttonDiv.innerHTML = `
    <div class="message-content">
    <p>📋 Get a customized quotation for your compliance needs:</p>
    <button onclick="openFeeModal()" class="fee-enquiry-btn">
    <i class="fas fa-rupee-sign"></i> Contact Us for Pricing
    </button>
    </div>
    <span class="time">${getCurrentTime()}</span>
    `;
    chatBox.appendChild(buttonDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function showTypingIndicator() {
    const chatBox = document.getElementById("chat-box");
    if (!chatBox) return;
    const typingDiv = document.createElement("div");
    typingDiv.className = "bot-message typing-container";
    typingDiv.id = "typing-indicator";
    typingDiv.innerHTML = `<div class="typing-indicator"><span></span><span></span><span></span></div>`;
    chatBox.appendChild(typingDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function removeTypingIndicator() {
    document.getElementById("typing-indicator")?.remove();
}

// ============================================================================
// ENHANCED ADD MESSAGE WITH BUTTON HANDLERS
// ============================================================================
function addMessage(content, type) {
    const chatBox = document.getElementById("chat-box");
    if (!chatBox) return;
    
    const messageDiv = document.createElement("div");
    messageDiv.className = type === 'user' ? "user-message" : "bot-message";
    
    const messageContent = document.createElement("div");
    messageContent.className = "message-content";
    messageContent.innerHTML = content;
    
    // Add click handlers to any service enquiry buttons in the message
    if (type === 'bot') {
        // Handle service enquiry buttons
        const serviceButtons = messageContent.querySelectorAll('button[onclick*="openServiceModal"]');
        serviceButtons.forEach(button => {
            try {
                const match = button.getAttribute('onclick').match(/'([^']+)'/);
                if (match && match[1]) {
                    const serviceName = match[1];
                    button.removeAttribute('onclick');
                    button.addEventListener('click', (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        openServiceModal(serviceName);
                    });
                }
            } catch (e) {
                console.error("Error processing service button:", e);
            }
        });
        
        // Handle fee enquiry buttons
        const feeButtons = messageContent.querySelectorAll('button[onclick*="openFeeModal"]');
        feeButtons.forEach(button => {
            button.removeAttribute('onclick');
            button.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                openFeeModal();
            });
        });
        
        // Handle download buttons
        const downloadButtons = messageContent.querySelectorAll('button[onclick*="openDownloadModal"]');
        downloadButtons.forEach(button => {
            try {
                const match = button.getAttribute('onclick').match(/'([^']+)',\s*'([^']+)'/);
                if (match && match[1] && match[2]) {
                    const state = match[1];
                    const actType = match[2];
                    button.removeAttribute('onclick');
                    button.addEventListener('click', (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        openDownloadModal(state, actType);
                    });
                }
            } catch (e) {
                console.error("Error processing download button:", e);
            }
        });
    }
    
    const timeSpan = document.createElement("span");
    timeSpan.className = "time";
    timeSpan.innerText = getCurrentTime();
    
    messageDiv.appendChild(messageContent);
    messageDiv.appendChild(timeSpan);
    chatBox.appendChild(messageDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function getCurrentTime() {
    const now = new Date();
    let hours = now.getHours();
    let minutes = now.getMinutes();
    const ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12 || 12;
    minutes = minutes < 10 ? '0' + minutes : minutes;
    return `${hours}:${minutes} ${ampm}`;
}

function checkOllamaStatus() {
    fetch("/check-ollama")
    .then(res => res.json())
    .then(data => {
        const statusElement = document.getElementById("ollama-status");
        if (statusElement) {
            if (data.status === "connected") {
                statusElement.innerHTML = `<i class="fas fa-circle" style="color: #00C851; font-size: 8px;"></i> <span>⚡ Fast Mode (${data.model})</span>`;
            } else {
                statusElement.innerHTML = `<i class="fas fa-circle" style="color: #ff4444; font-size: 8px;"></i> <span>Basic Mode</span>`;
            }
        }
    })
    .catch(() => {
        const statusElement = document.getElementById("ollama-status");
        if (statusElement) {
            statusElement.innerHTML = `<i class="fas fa-circle" style="color: #ff4444; font-size: 8px;"></i> <span>Basic Mode</span>`;
        }
    });
}

function showNotification(message, type) {
    document.querySelectorAll('.notification').forEach(n => n.remove());
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.innerHTML = `
    <i class="fas fa-${type === 'success' ? 'check-circle' : 'exclamation-circle'}"></i>
    <span>${message}</span>
    `;
    document.body.appendChild(notification);
    setTimeout(() => notification.remove(), 3000);
}

// Keyboard support
document.getElementById("user-input")?.addEventListener("keypress", function(e) {
    if (e.key === "Enter") sendMessage();
});

// Prevent modal close on inner click
document.querySelectorAll('.modal-content').forEach(content => {
    content.addEventListener('click', e => e.stopPropagation());
});

// Add dynamic styles
const style = document.createElement('style');
style.textContent = `
.service-enquiry-btn {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white; border: none; padding: 10px 20px;
    border-radius: 8px; cursor: pointer; font-size: 14px;
    font-weight: 500; margin-top: 10px; transition: all 0.3s ease;
    display: inline-flex; align-items: center; gap: 8px;
}
.service-enquiry-btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
}
.fee-enquiry-btn {
    background: linear-gradient(135deg, #ff9800 0%, #f57c00 100%);
    color: white; border: none; padding: 10px 20px;
    border-radius: 8px; cursor: pointer; font-size: 14px;
    font-weight: 500; margin-top: 10px; transition: all 0.3s ease;
    display: inline-flex; align-items: center; gap: 8px;
}
.fee-enquiry-btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 5px 15px rgba(255, 152, 0, 0.4);
}
.success-message-content {
    text-align: center; padding: 15px;
    background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    border-radius: 10px; border-left: 4px solid #28a745;
}
.success-message-content strong { color: #1a237e; }
.notification {
    position: fixed; top: 20px; right: 20px;
    padding: 12px 20px; border-radius: 8px;
    color: white; font-weight: 500; z-index: 10000;
    display: flex; align-items: center; gap: 10px;
    animation: slideIn 0.3s ease;
}
.notification.success { background: #28a745; }
.notification.error { background: #dc3545; }
@keyframes slideIn {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
}
.success-message {
    position: fixed; bottom: 20px; right: 20px;
    background: white; padding: 15px 20px;
    border-radius: 10px; box-shadow: 0 5px 20px rgba(0,0,0,0.15);
    display: flex; align-items: center; gap: 12px;
    z-index: 9999; animation: slideUp 0.3s ease;
}
@keyframes slideUp {
    from { transform: translateY(20px); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
}
.validation-icon {
    position: absolute; right: 12px; top: 50%;
    transform: translateY(-50%); font-size: 16px;
}
.validation-icon.valid { color: #28a745; }
.validation-icon.invalid { color: #dc3545; }
.error-tooltip {
    position: absolute; bottom: -25px; left: 0;
    background: #dc3545; color: white; padding: 4px 10px;
    border-radius: 4px; font-size: 11px; white-space: nowrap;
    z-index: 100; animation: fadeIn 0.2s ease;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
input.error, select.error {
    border-color: #dc3545 !important;
    background-color: #fff5f5 !important;
}
`;
document.head.appendChild(style);