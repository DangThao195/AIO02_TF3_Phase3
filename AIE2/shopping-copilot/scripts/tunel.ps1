$ErrorActionPreference = "Stop"

$REGION = "ap-southeast-1"
$BASTION_NAME = "techx-corp-tf3-bastion"
$EKS_CLUSTER_NAME = "techx-corp-tf3"
$LOCAL_PORT = "8443"

Write-Host "==> 1. Đang tra cứu Bastion Instance ID..." -ForegroundColor Cyan
$BASTION_ID = aws ec2 describe-instances `
    --region $REGION `
    --filters "Name=tag:Name,Values=$BASTION_NAME" "Name=instance-state-name,Values=running" `
    --query "Reservations[].Instances[].InstanceId" `
    --output text

if (-not $BASTION_ID) {
    Write-Error "Lỗi: Không tìm thấy Bastion Host đang chạy với tên '$BASTION_NAME'."
    exit 1
}
Write-Host "    Bastion ID: $BASTION_ID" -ForegroundColor Green

Write-Host "==> 2. Đang tra cứu EKS Cluster Endpoint..." -ForegroundColor Cyan
$EKS_ENDPOINT = aws eks describe-cluster `
    --name $EKS_CLUSTER_NAME `
    --region $REGION `
    --query "cluster.endpoint" `
    --output text

if (-not $EKS_ENDPOINT) {
    Write-Error "Lỗi: Không lấy được Endpoint của EKS cluster '$EKS_CLUSTER_NAME'."
    exit 1
}

$EKS_HOST = $EKS_ENDPOINT -replace "^https://", ""
Write-Host "    EKS Host: $EKS_HOST" -ForegroundColor Green

Write-Host "==> 3. Đang khởi tạo SSM Tunnel tới $EKS_HOST`:$LOCAL_PORT..." -ForegroundColor Cyan
aws ssm start-session `
    --target "$BASTION_ID" `
    --document-name AWS-StartPortForwardingSessionToRemoteHost `
    --parameters "host=$EKS_HOST,portNumber=443,localPortNumber=$LOCAL_PORT" `
    --region $REGION