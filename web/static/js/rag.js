// 파일 데이터 관리
let files = [];
let selectedFileId = null;
let currentViewMode = 'list';
let bulkLoadInProgress = false;
let bulkLoadAbortController = null;
let bulkLoadCompleted = false;
// const API_BASE_URL = window.DOC_API_BASE_URL || '/api';
const API_BASE_URL = "/rag";
const PDF_ICON_PATH = '/static/img/icon_pdf.png';
const VIEW_MODE_STORAGE_KEY = 'rag_explorer_view_mode';
const ACCORDION_STATE_STORAGE_KEY = 'rag_explorer_accordion_state';

// PDF 뷰어 상태
let pdfDoc = null;
let currentPage = 1;
let totalPages = 0;
let currentScale = 1.0;
let isPdfViewerActive = false;

// 초기화
document.addEventListener('DOMContentLoaded', function() {
    restoreViewMode();
    restoreAccordionState();
    setupViewToggle();
    setupAccordionToggle();
    setupUploadToggle();
    setupLoadAllButton();
    loadFiles();
    setupDragAndDrop();
    setupFileInput();
    setupResizer();
    setupPdfViewer();
});

function restoreViewMode() {
    const savedMode = localStorage.getItem(VIEW_MODE_STORAGE_KEY);
    currentViewMode = savedMode === 'grid' ? 'grid' : 'list';
}

function setViewMode(mode) {
    currentViewMode = mode === 'grid' ? 'grid' : 'list';
    localStorage.setItem(VIEW_MODE_STORAGE_KEY, currentViewMode);
    updateViewToggleButtons();
    renderFileList();
}

function setupViewToggle() {
    document.querySelectorAll('.view-toggle-btn').forEach(button => {
        button.addEventListener('click', () => {
            setViewMode(button.dataset.view || 'list');
        });
    });
    updateViewToggleButtons();
}

function setupUploadToggle() {
    const toggle = document.getElementById('uploadToggle');
    const content = document.getElementById('uploadContent');
    if (!toggle || !content) {
        return;
    }

    toggle.addEventListener('click', () => {
        const expanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', String(!expanded));
        content.classList.toggle('collapsed', expanded);

        const icon = toggle.querySelector('.upload-toggle-icon');
        if (icon) {
            icon.textContent = expanded ? '▸' : '▾';
        }
    });
}

function setupLoadAllButton() {
    const button = document.getElementById('loadAllBtn');
    const modal = document.getElementById('bulkLoadModal');
    const cancelButton = document.getElementById('bulkLoadCancelBtn');
    const startButton = document.getElementById('bulkLoadStartBtn');
    const progressFill = document.getElementById('bulkLoadProgressFill');
    const progressText = document.getElementById('bulkLoadProgressText');
    const estimateText = document.getElementById('bulkLoadEstimateText');
    const stepList = document.getElementById('bulkLoadStepList');
    const statusArea = document.getElementById('bulkLoadingStatus');
    const closeButton = document.getElementById('bulkLoadModalClose');

    if (!button || !modal) {
        return;
    }

    const updateModal = (percent, text, estimate, steps) => {
        if (progressFill) progressFill.style.width = `${percent}%`;
        if (progressText) progressText.textContent = text;
        if (estimateText) estimateText.textContent = estimate;
        if (stepList) {
            stepList.innerHTML = steps.map(step => `<li>${step}</li>`).join('');
        }
    };

    const openModal = () => {
        modal.classList.add('open');
        modal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('bulk-loading-active');
    };

    const closeModal = () => {
        if (bulkLoadInProgress) {
            return;
        }
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('bulk-loading-active');
    };

    const setStatusText = (message) => {
        if (statusArea) {
            statusArea.textContent = message;
        }
    };

    button.addEventListener('click', () => {
        if (bulkLoadInProgress) {
            return;
        }

        const pendingFiles = files.filter(file => !file.vectorLoaded && !file.loading);
        if (pendingFiles.length === 0) {
            return;
        }

        bulkLoadCompleted = false;
        if (startButton) {
            startButton.textContent = '적재 시작';
            startButton.disabled = false;
        }
        if (cancelButton) {
            cancelButton.textContent = '취소';
            cancelButton.disabled = false;
        }

        const estimatedMinutes = Math.max(1, Math.ceil(pendingFiles.length / 4));
        updateModal(0, '대기 중', `예상 시간: 약 ${estimatedMinutes}분`, ['적재 대상 문서를 확인 중입니다.', '문서별로 벡터 인덱스를 생성합니다.', '완료 후 상태를 갱신합니다.']);
        setStatusText('전체 적재 준비 중입니다. 시작 버튼을 눌러 진행하세요.');
        openModal();
    });

    closeButton?.addEventListener('click', closeModal);
    cancelButton?.addEventListener('click', () => {
        if (bulkLoadInProgress) {
            return;
        }
        if (bulkLoadAbortController) {
            bulkLoadAbortController.abort();
        }
        closeModal();
    });

    startButton?.addEventListener('click', async () => {
        if (bulkLoadCompleted) {
            closeModal();
            return;
        }

        const selectedMode = document.querySelector('input[name="bulkLoadMode"]:checked')?.value || 'skip';
        const pendingFiles = files.filter(file => !file.vectorLoaded && !file.loading);
        if (pendingFiles.length === 0) {
            alert('적재할 문서가 없습니다.');
            return;
        }

        bulkLoadInProgress = true;
        button.disabled = true;
        button.textContent = '적재 중...';
        startButton.disabled = true;
        startButton.textContent = '진행 중...';
        if (closeButton) {
            closeButton.disabled = true;
        }
        if (cancelButton) {
            cancelButton.disabled = true;
        }
        openModal();
        setStatusText('전체 적재를 시작했습니다. 진행 중에는 다른 적재를 막고 있습니다.');

        updateModal(5, '진행 중', '예상 시간: 약 1~3분', ['적재 대상을 확인했습니다.', '문서별 적재를 시작합니다.', '완료 후 결과를 반영합니다.']);

        bulkLoadAbortController = new AbortController();

        try {
            const response = await fetch(`${API_BASE_URL}/api/documents/load-all?mode=${selectedMode}`, {
                method: 'POST',
                signal: bulkLoadAbortController.signal
            });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.detail || '전체 적재에 실패했습니다.');
            }

            updateModal(100, '완료', `완료: ${result.loaded_count}개 적재`, ['모든 문서 적재가 끝났습니다.', '리스트를 새로고침합니다.']);
            setStatusText('');
            await loadFiles();
            bulkLoadCompleted = true;
            startButton.disabled = false;
            startButton.textContent = '확인';
            if (cancelButton) {
                cancelButton.textContent = '닫기';
            }
            if (closeButton) {
                closeButton.disabled = false;
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                setStatusText('전체 적재가 취소되었습니다.');
            } else {
                console.error(error);
                setStatusText('전체 적재 중 오류가 발생했습니다.');
                alert(`전체 적재 실패: ${error.message}`);
            }
        } finally {
            bulkLoadInProgress = false;
            bulkLoadAbortController = null;
            button.disabled = false;
            button.textContent = '전체 적재';
            if (closeButton) {
                closeButton.disabled = false;
            }
            if (cancelButton) {
                cancelButton.disabled = false;
            }
        }
    });
}

function updateViewToggleButtons() {
    document.querySelectorAll('.view-toggle-btn').forEach(button => {
        const isActive = (button.dataset.view || 'list') === currentViewMode;
        button.classList.toggle('active', isActive);
    });
}

function restoreAccordionState() {
    const savedState = localStorage.getItem(ACCORDION_STATE_STORAGE_KEY);
    if (!savedState) {
        return;
    }

    try {
        const state = JSON.parse(savedState);
        document.querySelectorAll('.section-toggle').forEach(button => {
            const section = button.dataset.section;
            const expanded = state[section] !== false;
            button.setAttribute('aria-expanded', String(expanded));
            const content = document.querySelector(`.accordion-content[data-section="${section}"]`);
            if (content) {
                content.classList.toggle('collapsed', !expanded);
            }
        });
    } catch (error) {
        console.error('Failed to restore accordion state:', error);
    }
}

function saveAccordionState() {
    const state = {};
    document.querySelectorAll('.section-toggle').forEach(button => {
        const section = button.dataset.section;
        state[section] = button.getAttribute('aria-expanded') === 'true';
    });
    localStorage.setItem(ACCORDION_STATE_STORAGE_KEY, JSON.stringify(state));
}

function setupAccordionToggle() {
    document.querySelectorAll('.section-toggle').forEach(button => {
        button.addEventListener('click', () => {
            const section = button.dataset.section;
            const expanded = button.getAttribute('aria-expanded') === 'true';
            const nextExpanded = !expanded;

            button.setAttribute('aria-expanded', String(nextExpanded));
            const content = document.querySelector(`.accordion-content[data-section="${section}"]`);
            if (content) {
                content.classList.toggle('collapsed', !nextExpanded);
            }
            saveAccordionState();
        });
    });
}

// stored_file_name 접두사로 파일 분류
function isCommonFile(storedFileName) {
    return storedFileName && storedFileName.startsWith('common_');
}

function isDocFile(storedFileName) {
    return storedFileName && storedFileName.startsWith('doc_');
}

function getCommonFiles() {
    return files.filter(f => isCommonFile(f.storedFileName));
}

function getDocFiles() {
    return files.filter(f => isDocFile(f.storedFileName));
}

// 파일 목록 로드 (백엔드 API 호출)
async function loadFiles() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/documents`);
        if (response.ok) {
            const data = await response.json();




            // 확인좀
            // const data = await response.json();

            console.log("🔥 API 응답 데이터:", data);
            console.log("🔥 문서 개수:", data.length);

            // files = data





            files = data
                .filter(doc => isCommonFile(doc.stored_file_name) || isDocFile(doc.stored_file_name))
                .map(doc => ({
                    id: doc.doc_id,
                    docId: doc.doc_id,
                    name: doc.original_file_name,
                    originalFileName: doc.original_file_name,
                    storedFileName: doc.stored_file_name,
                    size: doc.file_size || 0,
                    modified: doc.created_at,
                    uploaded: doc.created_at,
                    vectorLoaded: doc.is_loaded,
                    vectorLoadedDate: doc.loaded_at,
                    loading: false
                }));
            renderAll();
        } else {
            console.error('Failed to load files:', response.statusText);
        }
    } catch (error) {
        console.error('Error loading files:', error);
    }
}

// 좌측 탐색기 + 우측 테이블 동시 렌더링
function renderAll() {
    renderFileList();
    renderFileTable();
    updatePanelSummary();
}

// 좌측 파일 탐색기 렌더링
function renderFileList() {
    const commonList = document.getElementById('commonFileList');
    const docList = document.getElementById('docFileList');
    const commonCount = document.getElementById('commonCount');
    const docCount = document.getElementById('docCount');

    commonList.innerHTML = '';
    docList.innerHTML = '';
    commonList.classList.toggle('grid-view', currentViewMode === 'grid');
    docList.classList.toggle('grid-view', currentViewMode === 'grid');
    commonList.classList.toggle('list-view', currentViewMode !== 'grid');
    docList.classList.toggle('list-view', currentViewMode !== 'grid');

    const commonFiles = getCommonFiles();
    const docFiles = getDocFiles();

    commonCount.textContent = commonFiles.length;
    docCount.textContent = docFiles.length;

    if (commonFiles.length === 0) {
        commonList.innerHTML = '<div class="list-empty">등록된 공통 법률이 없습니다</div>';
    } else {
        commonFiles.forEach(file => {
            commonList.appendChild(createFileItem(file));
        });
    }

    if (docFiles.length === 0) {
        docList.innerHTML = '<div class="list-empty">등록된 일반 문서가 없습니다</div>';
    } else {
        docFiles.forEach(file => {
            docList.appendChild(createFileItem(file));
        });
    }
}

// 우측 파일 테이블 렌더링
function renderFileTable() {
    renderTableSection('commonTableBody', 'commonEmptyMsg', 'commonFileTable', getCommonFiles());
    renderTableSection('docTableBody', 'docEmptyMsg', 'docFileTable', getDocFiles());
}

function renderTableSection(tbodyId, emptyMsgId, tableId, fileList) {
    const tbody = document.getElementById(tbodyId);
    const emptyMsg = document.getElementById(emptyMsgId);
    const table = document.getElementById(tableId);

    tbody.innerHTML = '';

    if (fileList.length === 0) {
        table.style.display = 'none';
        emptyMsg.style.display = 'block';
        return;
    }

    table.style.display = 'table';
    emptyMsg.style.display = 'none';

    fileList.forEach(file => {
        const row = document.createElement('tr');
        row.dataset.fileId = file.id;
        row.className = 'file-table-row';
        if (selectedFileId === file.id) {
            row.classList.add('active');
        }

        row.innerHTML = `
            <td class="col-icon">
                <img src="${PDF_ICON_PATH}" alt="PDF" class="table-pdf-icon">
            </td>
            <td class="col-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</td>
            <td class="col-size">${formatFileSize(file.size)}</td>
            <td class="col-date">${formatDate(file.uploaded)}</td>
            <td class="col-status">
                ${
                    file.loading
                    ? `<span class="status-badge not-loaded">로딩중...</span>`
                    : file.vectorLoaded
                        ? `<span class="status-badge loaded">적재완료</span>`
                        : `
                        <span class="status-badge not-loaded"
                            onclick="loadVector(${file.id}, this)">
                            <span class="normal-text">미적재</span>
                            <span class="hover-text">적재하기</span>
                        </span>
                        `
                }
            </td>
            <td class="col-date">${file.vectorLoadedDate ? formatDate(file.vectorLoadedDate) : '-'}</td>
        `;

        row.onclick = function() {
            selectFile(file.id);
        };

        tbody.appendChild(row);
    });
}

function updatePanelSummary() {
    const total = files.length;
    document.getElementById('panelSubtitle').textContent =
        `총 ${total}개 문서 (공통 법률 ${getCommonFiles().length} · 일반 ${getDocFiles().length})`;
}

// 파일 아이템 생성 (좌측 탐색기)
function createFileItem(file) {
    const fileItem = document.createElement('div');
    fileItem.className = currentViewMode === 'grid' ? 'file-item grid-item' : 'file-item';
    fileItem.dataset.fileId = file.id;

    if (file.loading) {
        fileItem.classList.add('loading');
    }

    if (selectedFileId === file.id) {
        fileItem.classList.add('active');
    }

    const iconDiv = document.createElement('div');
    iconDiv.className = 'file-icon';
    const iconImg = document.createElement('img');
    iconImg.src = PDF_ICON_PATH;
    iconImg.alt = 'PDF';
    iconDiv.appendChild(iconImg);

    const contentDiv = document.createElement('div');
    contentDiv.className = 'file-item-content';

    const nameDiv = document.createElement('div');
    nameDiv.className = 'file-name';
    nameDiv.textContent = file.loading ? '업로드 중...' : file.name;
    nameDiv.title = file.name;

    contentDiv.appendChild(nameDiv);

    if (currentViewMode === 'grid') {
        const metaDiv = document.createElement('div');
        metaDiv.className = 'file-meta';
        metaDiv.textContent = formatFileSize(file.size);
        contentDiv.appendChild(metaDiv);
    }

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'delete-btn';
    deleteBtn.innerHTML = '×';
    deleteBtn.onclick = function(e) {
        e.stopPropagation();
        deleteFile(file.id);
    };

    fileItem.appendChild(iconDiv);
    fileItem.appendChild(contentDiv);
    fileItem.appendChild(deleteBtn);

    fileItem.onclick = function() {
        selectFile(file.id);
    };

    return fileItem;
}

// 파일 선택 (좌측·우측 동기화)
function selectFile(fileId) {
    const isSameSelection = selectedFileId === fileId;
    selectedFileId = isSameSelection ? null : fileId;

    document.querySelectorAll('.file-item').forEach(item => {
        item.classList.toggle('active', parseInt(item.dataset.fileId) === selectedFileId);
    });

    document.querySelectorAll('.file-table-row').forEach(row => {
        row.classList.toggle('active', parseInt(row.dataset.fileId) === selectedFileId);
    });

    if (selectedFileId === null) {
        if (isPdfViewerActive) {
            closePdfViewer();
        }
        document.getElementById('panelTitle').textContent = '문서 목록';
        return;
    }

    const file = files.find(f => f.id === selectedFileId);
    if (file) {
        openPdfViewer(file.docId);
    }
}

// 파일 삭제
async function deleteFile(fileId) {
    if (confirm('파일을 삭제하시겠습니까?')) {
        try {
            const response = await fetch(`${API_BASE_URL}/api/documents/${fileId}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                const fileIndex = files.findIndex(f => f.id === fileId);
                if (fileIndex > -1) {
                    files.splice(fileIndex, 1);
                    renderAll();

                    if (selectedFileId === fileId) {
                        selectedFileId = null;
                        document.getElementById('panelTitle').textContent = '문서 목록';
                    }
                }
            } else {
                alert('파일 삭제에 실패했습니다.');
                console.error('Delete failed:', response.statusText);
            }
        } catch (error) {
            alert('파일 삭제에 실패했습니다.');
            console.error('Error deleting file:', error);
        }
    }
}

// 드래그 앤 드롭 설정
function setupDragAndDrop() {
    const uploadArea = document.getElementById('uploadArea');
    const uploadContent = uploadArea.querySelector('.upload-content');

    uploadContent.addEventListener('dragover', function(e) {
        e.preventDefault();
        uploadContent.classList.add('drag-over');
    });

    uploadContent.addEventListener('dragleave', function(e) {
        e.preventDefault();
        uploadContent.classList.remove('drag-over');
    });

    uploadContent.addEventListener('drop', function(e) {
        e.preventDefault();
        uploadContent.classList.remove('drag-over');

        const droppedFiles = e.dataTransfer.files;
        if (droppedFiles.length > 0) {
            handleFileUpload(droppedFiles[0]);
        }
    });

    uploadContent.addEventListener('click', function() {
        document.getElementById('fileInput').click();
    });
}

// 파일 인풋 설정
function setupFileInput() {
    const fileInput = document.getElementById('fileInput');
    fileInput.addEventListener('change', function(e) {
        if (e.target.files.length > 0) {
            handleFileUpload(e.target.files[0]);
            fileInput.value = '';
        }
    });
}

// 파일 업로드 처리
async function handleFileUpload(file) {
    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
        alert('PDF 파일만 업로드할 수 있습니다.');
        return;
    }

    const isDuplicate = files.some(f => f.name === file.name && !f.loading);
    if (isDuplicate) {
        alert('동일한 이름의 파일이 이미 존재합니다.');
        return;
    }

    const tempId = Date.now();
    const isCommon = file.name[0] && file.name[0].match(/\d/);
    const tempStoredName = isCommon ? `common_temp_${file.name}` : `doc_temp_${file.name}`;

    const newFile = {
        id: tempId,
        name: file.name,
        storedFileName: tempStoredName,
        size: file.size,
        modified: new Date(file.lastModified).toISOString(),
        uploaded: new Date().toISOString(),
        vectorLoaded: false,
        vectorLoadedDate: null,
        loading: true
    };

    files.push(newFile);
    renderAll();

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_BASE_URL}/api/documents/upload`, {
            method: 'POST',
            body: formData
        });

        if (response.ok) {
            const result = await response.json();
            const fileIndex = files.findIndex(f => f.id === tempId);
            if (fileIndex > -1) {
                files.splice(fileIndex, 1);
            }

            await loadFiles();
            const refreshedFile = files.find(f => f.id === result.doc_id);
            if (refreshedFile) {
                selectFile(refreshedFile.id);
            }
        } else {
            const error = await response.json();
            alert(`업로드 실패: ${error.detail || '알 수 없는 오류'}`);

            const fileIndex = files.findIndex(f => f.id === tempId);
            if (fileIndex > -1) {
                files.splice(fileIndex, 1);
                renderAll();
            }
        }
    } catch (error) {
        alert('업로드 중 오류가 발생했습니다.');
        console.error('Upload error:', error);

        const fileIndex = files.findIndex(f => f.id === tempId);
        if (fileIndex > -1) {
            files.splice(fileIndex, 1);
            renderAll();
        }
    }
}

async function loadVector(docId, element) {

    if (element.classList.contains("loading")) {
        return;
    }

    element.classList.add("loading");
    element.innerHTML = "적재중...";

    try {
        const response = await fetch(
            `/api/documents/${docId}/load`,
            {
                method: "PUT"
            }
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.detail);
        }

        alert("벡터 적재 완료");

        await loadFiles();

    } catch(error) {

        console.error(error);
        alert("벡터 적재 실패 : " + error.message);

        element.classList.remove("loading");
        element.innerHTML = "적재하기";
    }
}

// HTML 이스케이프
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 파일 크기 포맷팅
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

// 날짜 포맷팅
function formatDate(dateString) {
    const date = new Date(dateString);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes}`;
}

// 리사이저 설정
function setupResizer() {
    const resizer = document.getElementById('resizer');
    const fileExplorer = document.getElementById('fileExplorer');

    let startX, startWidth;

    resizer.addEventListener('mousedown', function(e) {
        startX = e.clientX;
        startWidth = fileExplorer.offsetWidth;
        resizer.classList.add('resizing');

        // 텍스트 선택 방지
        document.body.style.userSelect = 'none';
        document.body.style.cursor = 'col-resize';

        document.addEventListener('mousemove', resize);
        document.addEventListener('mouseup', stopResize);
    });

    function resize(e) {
        const dx = e.clientX - startX;
        const newWidth = startWidth + dx;

        if (newWidth >= 200 && newWidth <= 800) {
            fileExplorer.style.width = newWidth + 'px';
        }
    }

    function stopResize() {
        resizer.classList.remove('resizing');
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
        document.removeEventListener('mousemove', resize);
        document.removeEventListener('mouseup', stopResize);
    }
}

// PDF 뷰어 설정
function setupPdfViewer() {
    const backToListBtn = document.getElementById('backToListBtn');
    const prevPageBtn = document.getElementById('prevPageBtn');
    const nextPageBtn = document.getElementById('nextPageBtn');
    const zoomInBtn = document.getElementById('zoomInBtn');
    const zoomOutBtn = document.getElementById('zoomOutBtn');

    if (backToListBtn) {
        backToListBtn.addEventListener('click', closePdfViewer);
    }

    if (prevPageBtn) {
        prevPageBtn.addEventListener('click', () => {
            if (currentPage > 1) {
                currentPage--;
                renderPage(currentPage);
            }
        });
    }

    if (nextPageBtn) {
        nextPageBtn.addEventListener('click', () => {
            if (currentPage < totalPages) {
                currentPage++;
                renderPage(currentPage);
            }
        });
    }

    if (zoomInBtn) {
        zoomInBtn.addEventListener('click', () => {
            if (currentScale < 3.0) {
                currentScale += 0.25;
                renderPage(currentPage);
            }
        });
    }

    if (zoomOutBtn) {
        zoomOutBtn.addEventListener('click', () => {
            if (currentScale > 0.5) {
                currentScale -= 0.25;
                renderPage(currentPage);
            }
        });
    }
}

// PDF 뷰어 열기
async function openPdfViewer(docId) {
    const file = files.find(f => f.docId === docId);
    if (!file) return;

    const panelContent = document.getElementById('panelContent');
    const pdfViewerContainer = document.getElementById('pdfViewerContainer');
    const backToListBtn = document.getElementById('backToListBtn');
    const loadAllBtn = document.getElementById('loadAllBtn');
    const panelTitle = document.getElementById('panelTitle');
    const panelSubtitle = document.getElementById('panelSubtitle');

    if (panelContent) panelContent.style.display = 'none';
    if (pdfViewerContainer) pdfViewerContainer.style.display = 'flex';
    if (backToListBtn) backToListBtn.style.display = 'inline-block';
    if (loadAllBtn) loadAllBtn.style.display = 'none';
    if (panelTitle) panelTitle.textContent = file.originalFileName;
    if (panelSubtitle) panelSubtitle.style.display = 'none';

    isPdfViewerActive = true;

    try {
        // PDF 파일을 Blob으로 가져오기
        const response = await fetch(`${API_BASE_URL}/api/documents/${docId}/file`);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `PDF 파일을 불러오는데 실패했습니다. (Status: ${response.status})`);
        }

        const blob = await response.blob();
        const arrayBuffer = await blob.arrayBuffer();

        // PDF 문서 로드
        pdfDoc = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
        totalPages = pdfDoc.numPages;
        currentPage = 1;
        currentScale = 1.0;

        updatePdfViewerInfo();
        renderPage(currentPage);

    } catch (error) {
        console.error('PDF 로드 오류:', error);
        alert('PDF를 불러오는데 실패했습니다: ' + error.message);
        closePdfViewer();
    }
}

// PDF 뷰어 닫기
function closePdfViewer() {
    const panelContent = document.getElementById('panelContent');
    const pdfViewerContainer = document.getElementById('pdfViewerContainer');
    const backToListBtn = document.getElementById('backToListBtn');
    const loadAllBtn = document.getElementById('loadAllBtn');
    const panelTitle = document.getElementById('panelTitle');
    const panelSubtitle = document.getElementById('panelSubtitle');

    if (panelContent) panelContent.style.display = 'block';
    if (pdfViewerContainer) pdfViewerContainer.style.display = 'none';
    if (backToListBtn) backToListBtn.style.display = 'none';
    if (loadAllBtn) loadAllBtn.style.display = 'inline-block';
    if (panelTitle) panelTitle.textContent = '문서 목록';
    if (panelSubtitle) {
        panelSubtitle.style.display = 'inline';
        panelSubtitle.textContent = `총 ${files.length}개 문서`;
    }

    isPdfViewerActive = false;
    pdfDoc = null;
    currentPage = 1;
    totalPages = 0;
    currentScale = 1.0;

    // 캔버스 초기화
    const canvas = document.getElementById('pdfCanvas');
    if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
}

// PDF 페이지 렌더링
async function renderPage(pageNum) {
    if (!pdfDoc) return;

    const canvas = document.getElementById('pdfCanvas');
    const ctx = canvas.getContext('2d');

    try {
        const page = await pdfDoc.getPage(pageNum);
        const viewport = page.getViewport({ scale: currentScale });

        canvas.height = viewport.height;
        canvas.width = viewport.width;

        const renderContext = {
            canvasContext: ctx,
            viewport: viewport
        };

        await page.render(renderContext).promise;
        updatePdfViewerInfo();

    } catch (error) {
        console.error('페이지 렌더링 오류:', error);
    }
}

// PDF 뷰어 정보 업데이트
function updatePdfViewerInfo() {
    const pageInfo = document.getElementById('pageInfo');
    const zoomInfo = document.getElementById('zoomInfo');

    if (pageInfo) {
        pageInfo.textContent = `${currentPage} / ${totalPages}`;
    }

    if (zoomInfo) {
        zoomInfo.textContent = `${Math.round(currentScale * 100)}%`;
    }
}
