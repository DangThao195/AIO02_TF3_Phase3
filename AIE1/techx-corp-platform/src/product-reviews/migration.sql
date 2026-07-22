-- Migration script for productreviews
-- Step 1: Add is_safe column to reviews.productreviews if it does not exist
ALTER TABLE reviews.productreviews ADD COLUMN IF NOT EXISTS is_safe BOOLEAN DEFAULT TRUE;

-- Step 2: Create composite index for optimized lookups by product_id and is_safe
CREATE INDEX IF NOT EXISTS productreviews_prod_safe_idx ON reviews.productreviews (product_id, is_safe);
