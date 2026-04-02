const { createApp, ref, onMounted } = Vue;

const API_BASE = "http://127.0.0.1:8000/api/v1";

createApp({
  setup() {
    const tab = ref("report");
    const reports = ref([]);
    const reportPage = ref(1);
    const reportPages = ref(1);
    const reportTotal = ref(0);
    const reportPageSize = ref(20);
    const currentReport = ref(null);
    const graphReport = ref(null);
    const lastRun = ref(null);
    const generateError = ref("");
    const loading = ref({ generate: false, list: false, articles: false, recompute: false });
    const progressMsg = ref("");
    const filters = ref({ source: "", start: "", end: "", sort: "score_desc" });
    const reportOptions = ref({ fastMode: true });
    const articles = ref([]);
    const tablePage = ref(1);
    const tablePageSize = ref(30);
    const tableTotal = ref(0);
    const tablePages = ref(1);
    const graphOptions = ref({ days: 365, maxArticles: 220 });
    const graphMeta = ref(null);
    const graphError = ref("");
    let fg = null;

    const switchTab = (t) => {
      tab.value = t;
      if (t === "report") fetchReportList();
      if (t === "table" && articles.value.length === 0) fetchArticles();
      if (t === "graph") setTimeout(fetchWarehouseGraph, 50);
    };

    const api = axios.create({ baseURL: API_BASE });

    const generateReport = async () => {
      loading.value.generate = true;
      progressMsg.value = "正在生成最近 7 天日报…";
      generateError.value = "";
      try {
        const { data } = await api.post("/reports/generate", null, {
          params: { days: 7, language: "mixed", fast_mode: reportOptions.value.fastMode },
        });
        const d = data?.data;
        lastRun.value = {
          date: d?.date,
          duration: d?.duration_seconds?.toFixed(2),
          articles: d?.articles_analyzed,
        };
        await fetchReportList();
        if (d?.report_id) await loadReport(d.report_id);
      } catch (e) {
        generateError.value = e?.response?.data?.message || e.message;
      } finally {
        loading.value.generate = false;
        progressMsg.value = "";
      }
    };

    const fetchLatest7DaysData = async () => {
      progressMsg.value = "正在获取最近 7 天抓取数据...";
      const now = new Date();
      const since = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      filters.value.start = since.toISOString().slice(0, 10);
      filters.value.end = now.toISOString().slice(0, 10);
      tablePage.value = 1;
      reportPage.value = 1;
      await Promise.all([fetchArticles(), fetchReportList()]);
      progressMsg.value = "";
    };

    const fetchReportList = async () => {
      loading.value.list = true;
      try {
        const { data } = await api.get("/reports/", {
          params: { page: reportPage.value, page_size: reportPageSize.value },
        });
        reports.value = data?.data?.items || [];
        reportPages.value = data?.data?.pages || 1;
        reportTotal.value = data?.data?.total || 0;
      } finally {
        loading.value.list = false;
      }
    };

    const loadReport = async (reportId) => {
      const { data } = await api.get(`/reports/by-id/${reportId}`);
      currentReport.value = data?.data;
      graphReport.value = currentReport.value;
      drawGraph();
    };

    const prevReportPage = async () => {
      if (reportPage.value <= 1) return;
      reportPage.value -= 1;
      await fetchReportList();
    };

    const nextReportPage = async () => {
      if (reportPage.value >= reportPages.value) return;
      reportPage.value += 1;
      await fetchReportList();
    };

    const fetchArticles = async () => {
      loading.value.articles = true;
      try {
        const params = {
          page: tablePage.value,
          page_size: tablePageSize.value,
          include_signals: true,
        };
        if (filters.value.source) params.source = filters.value.source;
        if (filters.value.start) params.start_date = filters.value.start;
        if (filters.value.end) params.end_date = filters.value.end;

        const { data } = await api.get("/articles/", { params });
        let items = data?.data?.items || [];
        tableTotal.value = data?.data?.total || 0;
        tablePages.value = data?.data?.pages || 1;

        if (filters.value.sort === "score_desc") {
          items = items.sort((a, b) => (b.composite_score || 0) - (a.composite_score || 0));
        } else if (filters.value.sort === "score_asc") {
          items = items.sort((a, b) => (a.composite_score || 0) - (b.composite_score || 0));
        } else if (filters.value.sort === "time_asc") {
          items = items.sort((a, b) => (a.published_at || "").localeCompare(b.published_at || ""));
        } else {
          items = items.sort((a, b) => (b.published_at || "").localeCompare(a.published_at || ""));
        }
        articles.value = items;
      } finally {
        loading.value.articles = false;
      }
    };

    const recalculateHeat = async () => {
      loading.value.recompute = true;
      progressMsg.value = "正在重新计算热度，请稍候...";
      generateError.value = "";
      try {
        let days = 7;
        if (filters.value.start && filters.value.end) {
          const start = new Date(filters.value.start);
          const end = new Date(filters.value.end);
          const diffMs = end.getTime() - start.getTime();
          const diffDays = Math.floor(diffMs / (24 * 60 * 60 * 1000)) + 1;
          if (!Number.isNaN(diffDays) && diffDays > 0) {
            days = Math.min(30, Math.max(1, diffDays));
          }
        }
        await api.post("/signals/compute", null, {
          params: { days, language: "mixed", save_to_db: true },
        });
        await fetchArticles();
      } catch (e) {
        generateError.value = e?.response?.data?.message || e.message;
      } finally {
        loading.value.recompute = false;
        progressMsg.value = "";
      }
    };

    const applyFilters = async () => {
      tablePage.value = 1;
      await fetchArticles();
    };

    const setSort = async (sortKey) => {
      filters.value.sort = sortKey;
      await applyFilters();
    };

    const prevPage = async () => {
      if (tablePage.value <= 1) return;
      tablePage.value -= 1;
      await fetchArticles();
    };

    const nextPage = async () => {
      if (tablePage.value >= tablePages.value) return;
      tablePage.value += 1;
      await fetchArticles();
    };

    const setGraphFromReport = () => {
      tab.value = "graph";
      fetchWarehouseGraph();
    };

    const fetchWarehouseGraph = async () => {
      loading.value.list = true;
      graphError.value = "";
      try {
        const { data } = await api.get("/signals/network", {
          params: {
            days: graphOptions.value.days,
            max_articles: graphOptions.value.maxArticles,
          },
        });
        graphMeta.value = data?.data?.meta || null;
        drawGraph(data?.data || { nodes: [], links: [] });
      } catch (e) {
        graphError.value = e?.response?.data?.message || e.message;
      } finally {
        loading.value.list = false;
      }
    };

    const drawGraph = (graphPayload) => {
      const el = document.getElementById("graph");
      if (!el) return;
      const nodes = graphPayload?.nodes || [];
      const links = graphPayload?.links || [];

      if (!fg) fg = ForceGraph()(el);
      fg
        .graphData({ nodes, links })
        .nodeLabel((n) => n.label)
        .nodeRelSize(6)
        .nodeColor((n) => {
          const map = {
            article: "#ffb25b",
            source: "#2575d9",
            tag: "#1fa57a",
          };
          return map[n.type] || "#999";
        })
        .linkColor((l) => (l.type === "source_tag_affinity" ? "rgba(37,117,217,0.35)" : "rgba(120,120,120,0.5)"));
    };

    onMounted(() => {
      fetchReportList();
    });

    return {
      tab,
      reports,
      reportPage,
      reportPages,
      reportTotal,
      currentReport,
      graphReport,
      lastRun,
      generateError,
      loading,
      progressMsg,
      filters,
      reportOptions,
      articles,
      tablePage,
      tablePageSize,
      tableTotal,
      tablePages,
      graphOptions,
      graphMeta,
      graphError,
      switchTab,
      generateReport,
      fetchLatest7DaysData,
      fetchReportList,
      loadReport,
      prevReportPage,
      nextReportPage,
      fetchArticles,
      recalculateHeat,
      applyFilters,
      setSort,
      prevPage,
      nextPage,
      fetchWarehouseGraph,
      setGraphFromReport,
    };
  },
}).mount("#app");
