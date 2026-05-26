<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <!-- Budget control card -->
      <div class="card budget-card">
        <label for="budget-slider">{{ t('restocking.budget.label') }}</label>
        <div class="budget-row">
          <input
            id="budget-slider"
            type="range"
            min="0"
            max="200000"
            step="1000"
            v-model.number="budget"
            class="budget-slider"
          />
          <div class="budget-value">{{ formatMoney(budget) }}</div>
        </div>
        <div class="budget-stats">
          <div><span class="stat-key">{{ t('restocking.budget.itemsSelected', { selected: selectedCount, total: recommendableItems.length }) }}</span></div>
          <div><span class="stat-key">{{ t('restocking.budget.committed') }}:</span> <strong>{{ formatMoney(totalCost) }}</strong></div>
          <div><span class="stat-key">{{ t('restocking.budget.remaining') }}:</span> <strong>{{ formatMoney(remainingBudget) }}</strong></div>
        </div>
      </div>

      <!-- Empty states (mutually exclusive) -->
      <div v-if="budget === 0" class="empty-state">{{ t('restocking.empty.noBudget') }}</div>
      <div v-else-if="recommendableItems.length === 0" class="empty-state">{{ t('restocking.empty.allMet') }}</div>
      <div v-else-if="selectedItems.length === 0" class="empty-state">{{ t('restocking.empty.noneFit') }}</div>

      <!-- Recommendations table -->
      <div v-if="recommendableItems.length > 0" class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.budget.itemsSelected', { selected: selectedCount, total: recommendableItems.length }) }}</h3>
        </div>
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th style="width:60px">{{ t('restocking.table.include') }}</th>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.currentDemand') }}</th>
                <th>{{ t('restocking.table.forecastedDemand') }}</th>
                <th>{{ t('restocking.table.gap') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineCost') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in recommendableItems"
                :key="row.sku"
                :class="{ 'row-muted': !isIncluded(row.sku) }"
              >
                <td>
                  <input
                    type="checkbox"
                    :checked="!deselectedSkus.has(row.sku)"
                    @change="toggleItem(row.sku)"
                  />
                </td>
                <td><strong>{{ row.sku }}</strong></td>
                <td>{{ translateProductName(row.name) }}</td>
                <td>{{ row.currentDemand }}</td>
                <td><strong>{{ row.forecastedDemand }}</strong></td>
                <td>{{ row.gap }}</td>
                <td>{{ formatMoney(row.unitCost) }}</td>
                <td><strong>{{ formatMoney(row.lineCost) }}</strong></td>
                <td>{{ t('restocking.table.days', { count: row.leadTimeDays }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Place Order footer -->
      <div class="place-order-bar" v-if="recommendableItems.length > 0">
        <div v-if="submitSuccess" class="success-banner">{{ submitSuccess }}</div>
        <div v-if="submitError" class="error">{{ submitError }}</div>
        <button class="place-order-btn" :disabled="!canPlaceOrder" @click="placeOrder">
          <span v-if="submitting">{{ t('restocking.submitting') }}</span>
          <span v-else>{{ t('restocking.placeOrder') }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()

    // State
    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const inventory = ref([])
    const budget = ref(50000)
    const deselectedSkus = ref(new Set())
    const submitting = ref(false)
    const submitError = ref(null)
    const submitSuccess = ref(null)

    // onMounted: parallel fetch
    onMounted(async () => {
      loading.value = true
      error.value = null
      try {
        const [forecastsData, inventoryData] = await Promise.all([
          api.getDemandForecasts(),
          api.getInventory()
        ])
        forecasts.value = forecastsData
        inventory.value = inventoryData
      } catch (err) {
        error.value = 'Failed to load restocking data: ' + err.message
      } finally {
        loading.value = false
      }
    })

    // Computed
    const currencySymbol = computed(() => currentCurrency.value === 'JPY' ? '¥' : '$')

    const recommendableItems = computed(() => {
      const inventoryMap = new Map()
      inventory.value.forEach(item => {
        inventoryMap.set(item.sku, item)
      })

      const rows = []
      forecasts.value.forEach(forecast => {
        const inv = inventoryMap.get(forecast.item_sku)
        if (!inv) return
        if (forecast.forecasted_demand <= forecast.current_demand) return
        if (inv.unit_cost <= 0) return

        const gap = forecast.forecasted_demand - forecast.current_demand
        const lineCost = gap * inv.unit_cost

        rows.push({
          sku: forecast.item_sku,
          name: forecast.item_name,
          currentDemand: forecast.current_demand,
          forecastedDemand: forecast.forecasted_demand,
          gap,
          unitCost: inv.unit_cost,
          lineCost,
          leadTimeDays: inv.lead_time_days
        })
      })

      // Sort by gap descending
      rows.sort((a, b) => b.gap - a.gap)
      return rows
    })

    const selectedItems = computed(() => {
      let runningTotal = 0
      const result = []

      for (const row of recommendableItems.value) {
        if (deselectedSkus.value.has(row.sku)) continue
        if (runningTotal + row.lineCost <= budget.value) {
          result.push(row)
          runningTotal += row.lineCost
        }
        // Items that don't fit are skipped (no re-packing)
      }

      return result
    })

    const totalCost = computed(() => {
      return selectedItems.value.reduce((sum, row) => sum + row.lineCost, 0)
    })

    const remainingBudget = computed(() => {
      const rem = budget.value - totalCost.value
      return rem < 0 ? 0 : rem
    })

    const selectedCount = computed(() => selectedItems.value.length)

    const canPlaceOrder = computed(() => selectedItems.value.length > 0 && !submitting.value)

    // Methods
    const toggleItem = (sku) => {
      const newSet = new Set(deselectedSkus.value)
      if (newSet.has(sku)) {
        newSet.delete(sku)
      } else {
        newSet.add(sku)
      }
      deselectedSkus.value = newSet
    }

    const isIncluded = (sku) => {
      const selectedSet = new Set(selectedItems.value.map(row => row.sku))
      return selectedSet.has(sku)
    }

    const formatMoney = (n) => {
      return currencySymbol.value + n.toLocaleString(undefined, { maximumFractionDigits: 0 })
    }

    const placeOrder = async () => {
      submitting.value = true
      submitError.value = null
      submitSuccess.value = null

      const items = selectedItems.value.map(row => ({
        sku: row.sku,
        name: row.name,
        quantity: row.gap,
        unit_cost: row.unitCost,
        lead_time_days: row.leadTimeDays
      }))

      try {
        await api.submitRestockingOrder({ items })
        submitSuccess.value = t('restocking.success')
      } catch (err) {
        submitError.value = t('restocking.error')
      } finally {
        submitting.value = false
      }
    }

    return {
      t,
      translateProductName,
      loading,
      error,
      forecasts,
      inventory,
      budget,
      deselectedSkus,
      submitting,
      submitError,
      submitSuccess,
      currencySymbol,
      recommendableItems,
      selectedItems,
      totalCost,
      remainingBudget,
      selectedCount,
      canPlaceOrder,
      toggleItem,
      isIncluded,
      formatMoney,
      placeOrder
    }
  }
}
</script>

<style scoped>
.restocking {
  padding: 0;
}

.budget-card {
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}

.budget-card label {
  display: block;
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 1rem;
}

.budget-row {
  display: flex;
  align-items: center;
  gap: 1.5rem;
}

.budget-slider {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  accent-color: #2563eb;
  cursor: pointer;
  appearance: auto;
}

.budget-value {
  font-size: 1.75rem;
  font-weight: 700;
  color: #0f172a;
  min-width: 160px;
  text-align: right;
}

.budget-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 2rem;
  border-top: 1px solid #e2e8f0;
  padding-top: 1rem;
  margin-top: 1rem;
}

.budget-stats > div {
  color: #0f172a;
  font-size: 0.9rem;
}

.stat-key {
  color: #64748b;
  font-size: 0.875rem;
}

.budget-stats strong {
  color: #0f172a;
  font-weight: 600;
}

.row-muted {
  opacity: 0.4;
}

.empty-state {
  text-align: center;
  color: #64748b;
  padding: 2rem;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  background: #f8fafc;
  margin: 1rem 0;
  font-size: 0.938rem;
}

.place-order-bar {
  margin-top: 1.5rem;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.75rem;
}

.place-order-btn {
  background: #0f172a;
  color: white;
  padding: 0.75rem 2rem;
  font-size: 1rem;
  font-weight: 600;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.place-order-btn:hover:not(:disabled) {
  background: #1e293b;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.success-banner {
  background: #d1fae5;
  border: 1px solid #6ee7b7;
  color: #065f46;
  padding: 1rem;
  border-radius: 8px;
  font-size: 0.938rem;
  width: 100%;
}
</style>
