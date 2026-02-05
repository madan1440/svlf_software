const state = {
  rows: [],
  emis: [],
  filtered: [],
};

const elements = {
  searchInput: document.getElementById("searchInput"),
  typeFilter: document.getElementById("typeFilter"),
  statusFilter: document.getElementById("statusFilter"),
  searchButton: document.getElementById("searchButton"),
  totalCount: document.getElementById("totalCount"),
  stockCount: document.getElementById("stockCount"),
  soldCount: document.getElementById("soldCount"),
  vehicleTableBody: document.getElementById("vehicleTableBody"),
  vehicleDetails: document.getElementById("vehicleDetails"),
  sellerDetails: document.getElementById("sellerDetails"),
  buyerDetails: document.getElementById("buyerDetails"),
  buyerEmpty: document.getElementById("buyerEmpty"),
  detailName: document.getElementById("detailName"),
  detailMeta: document.getElementById("detailMeta"),
  detailNumber: document.getElementById("detailNumber"),
  sellerName: document.getElementById("sellerName"),
  sellerPhone: document.getElementById("sellerPhone"),
  sellerCity: document.getElementById("sellerCity"),
  sellerBuyValue: document.getElementById("sellerBuyValue"),
  sellerBuyDate: document.getElementById("sellerBuyDate"),
  sellerComments: document.getElementById("sellerComments"),
  buyerName: document.getElementById("buyerName"),
  buyerPhone: document.getElementById("buyerPhone"),
  buyerSaleValue: document.getElementById("buyerSaleValue"),
  buyerFinanceAmount: document.getElementById("buyerFinanceAmount"),
  buyerEmiAmount: document.getElementById("buyerEmiAmount"),
  buyerTenure: document.getElementById("buyerTenure"),
  buyerSaleDate: document.getElementById("buyerSaleDate"),
  emiTableBody: document.getElementById("emiTableBody"),
  backToDashboard: document.getElementById("backToDashboard"),
};

const csvParse = (text) => {
  const rows = [];
  let row = [];
  let value = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];
    if (char === "\"") {
      if (inQuotes && next === "\"") {
        value += "\"";
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === "," && !inQuotes) {
      row.push(value);
      value = "";
    } else if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") {
        i += 1;
      }
      row.push(value);
      if (row.some((cell) => cell !== "")) {
        rows.push(row);
      }
      row = [];
      value = "";
    } else {
      value += char;
    }
  }
  if (value.length || row.length) {
    row.push(value);
    if (row.some((cell) => cell !== "")) {
      rows.push(row);
    }
  }
  return rows;
};

const csvToObjects = (text) => {
  const rows = csvParse(text);
  if (rows.length === 0) {
    return [];
  }
  const [header, ...data] = rows;
  return data.map((cols) => {
    const obj = {};
    header.forEach((key, index) => {
      obj[key] = cols[index] ?? "";
    });
    return obj;
  });
};

const loadData = async () => {
  const [fullResp, emiResp] = await Promise.all([
    fetch("full.csv"),
    fetch("emi.csv"),
  ]);
  const [fullText, emiText] = await Promise.all([
    fullResp.text(),
    emiResp.text(),
  ]);
  state.rows = csvToObjects(fullText);
  state.emis = csvToObjects(emiText);
  state.filtered = state.rows.slice();
  renderSummary();
  renderTable();
};

const renderSummary = () => {
  elements.totalCount.textContent = state.rows.length.toString();
  elements.stockCount.textContent = state.rows.filter((row) => row.status === "Stock").length.toString();
  elements.soldCount.textContent = state.rows.filter((row) => row.status === "Sold").length.toString();
};

const renderTable = () => {
  elements.vehicleTableBody.innerHTML = "";
  state.filtered.forEach((row, index) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${index + 1}</td>
      <td>${row.type || ""}</td>
      <td>${row.name || ""}</td>
      <td>${row.brand || ""}</td>
      <td>${row.model || ""}</td>
      <td><a href="#" class="link" data-vehicle="${row.vehicle_id}">${row.number || ""}</a></td>
      <td>${row.status === "Stock" ? "<span class=\"badge stock\">In Stock</span>" : "<span class=\"badge sold\">Sold</span>"}</td>
    `;
    elements.vehicleTableBody.appendChild(tr);
  });
};

const applyFilters = () => {
  const q = elements.searchInput.value.trim().toLowerCase();
  const type = elements.typeFilter.value;
  const status = elements.statusFilter.value;
  state.filtered = state.rows.filter((row) => {
    if (type !== "ALL" && row.type !== type) {
      return false;
    }
    if (status !== "ALL" && row.status !== status) {
      return false;
    }
    if (!q) {
      return true;
    }
    const haystack = `${row.name || ""} ${row.brand || ""} ${row.model || ""} ${row.number || ""}`.toLowerCase();
    return haystack.includes(q);
  });
  renderTable();
};

const showDetails = (vehicleId) => {
  const row = state.rows.find((item) => item.vehicle_id === vehicleId);
  if (!row) {
    return;
  }
  elements.vehicleDetails.classList.remove("hidden");
  elements.sellerDetails.classList.remove("hidden");
  elements.detailName.textContent = `${row.name || ""} (${row.type || ""})`;
  elements.detailMeta.textContent = `${row.brand || ""} • ${row.model || ""} • ${row.color || ""}`;
  elements.detailNumber.textContent = row.number || "";
  elements.sellerName.textContent = row.seller_name || "";
  elements.sellerPhone.textContent = row.seller_phone || "";
  elements.sellerCity.textContent = row.seller_city || "";
  elements.sellerBuyValue.textContent = row.buy_value || "";
  elements.sellerBuyDate.textContent = row.buy_date || "";
  elements.sellerComments.textContent = row.comments || "";

  if (row.buyer_id) {
    elements.buyerDetails.classList.remove("hidden");
    elements.buyerEmpty.classList.add("hidden");
    elements.buyerName.textContent = row.buyer_name || "";
    elements.buyerPhone.textContent = row.buyer_phone || "";
    elements.buyerSaleValue.textContent = row.sale_value || "";
    elements.buyerFinanceAmount.textContent = row.finance_amount || "";
    elements.buyerEmiAmount.textContent = row.emi_amount || "";
    elements.buyerTenure.textContent = row.tenure || "";
    elements.buyerSaleDate.textContent = row.sale_date || "";
    const emis = state.emis
      .filter((emi) => emi.buyer_id === row.buyer_id)
      .sort((a, b) => Number(a.emi_no || 0) - Number(b.emi_no || 0));
    elements.emiTableBody.innerHTML = "";
    emis.forEach((emi) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${emi.emi_no || ""}</td>
        <td>${emi.due_date || ""}</td>
        <td>₹${emi.amount || ""}</td>
        <td>${emi.status || ""}</td>
      `;
      elements.emiTableBody.appendChild(tr);
    });
  } else {
    elements.buyerDetails.classList.add("hidden");
    elements.buyerEmpty.classList.remove("hidden");
  }
  window.location.hash = `vehicle-${vehicleId}`;
};

const hideDetails = () => {
  elements.vehicleDetails.classList.add("hidden");
  elements.sellerDetails.classList.add("hidden");
  elements.buyerDetails.classList.add("hidden");
  elements.buyerEmpty.classList.add("hidden");
  window.location.hash = "";
};

elements.searchButton.addEventListener("click", applyFilters);
elements.searchInput.addEventListener("input", applyFilters);
elements.typeFilter.addEventListener("change", applyFilters);
elements.statusFilter.addEventListener("change", applyFilters);

elements.vehicleTableBody.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-vehicle]");
  if (link) {
    event.preventDefault();
    showDetails(link.dataset.vehicle);
  }
});

elements.backToDashboard.addEventListener("click", (event) => {
  event.preventDefault();
  hideDetails();
});

window.addEventListener("hashchange", () => {
  const match = window.location.hash.match(/^#vehicle-(.+)$/);
  if (match) {
    showDetails(match[1]);
  } else {
    hideDetails();
  }
});

loadData();
